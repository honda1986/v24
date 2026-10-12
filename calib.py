#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib.py -- 予想の精度（予想した確率どおりに当たっているか）を日別に集計する

予想サイトの「予想の精度」が読む stats/calib.json を作る。

  python calib.py --kfile ../v22/kfile                     毎朝（runner.py motor / prefetch）
  python calib.py --kfile ../v22/kfile --backfill 20260901 過去の日を git の履歴から作り直す

★history.json の races[].lanes（各艇のモデル確率 p と市場確率 q）は
  14日で消える（yosou.KEEP_DETAIL_DAYS）。消える前に毎朝ここで集計して残す。
  一度集計した日は、レース数が増えたときだけ書き直す（消えた後に0件で上書きしない）。
★モデルと市場（判定時のオッズ）を同じレースで数える。モデルの較正が良くても、
  市場も同じくらい良ければ「市場より当たる」ことにはならない。並べて見るためのもの。
★数えるのはモデルを回したレースだけ（淡水・気象が取れない回などは入らない）。

集計の形（1日ぶん）:
  "n":   数えたレース数
  "p" / "q":  モデル / 市場 それぞれ
     "cal": 確率の帯ごとに [艇数, 1着の数, 確率の和]（全艇ぶん。帯は BANDS）
     "fav": 本命（確率が最大の艇）[数, 1着の数, 確率の和] を 全体・混戦・中位・堅い の順
     "ll":  1着の対数損失の和（÷n で平均）
  "t8": 3連単 出やすい順の上位8組 [レース数, 的中, 確率の和]
  "t1": 3連単 予想1位の組 [レース数, 的中]
"""
import argparse
import json
import math
import os
import subprocess
from datetime import datetime, timedelta, timezone

import settle as S

JST = timezone(timedelta(hours=9))
SITE = "history.json"
OUT = "stats/calib.json"
VERSION = 1
BANDS = [0, 0.05, 0.10, 0.20, 0.30, 0.45, 0.60, 1.01]   # v23 の画面と同じ帯
JUDGE = [0, 0.38, 0.55, 1.01]                          # 混戦 / 中位 / 堅い（v23 と同じ）


def band(p, edges):
    for i in range(len(edges) - 1):
        if edges[i] <= p < edges[i + 1]:
            return i
    return len(edges) - 2


def races_of(day):
    """その日の、内訳(lanes)が残っているレース（モデルを回した全レース）。

    ★races（見た全レース）の内訳だけを土台にする。picks（買ったレース）にも
      内訳はあるが、races の内訳が消えた古い日に picks だけで数えると、
      「モデルが市場と食い違ったレース」だけを数えることになり偏る。
      picks / ana からは、races に無い「出やすい順」だけを借りる。
    """
    out = {}
    for r in day.get("races") or []:
        ln = r.get("lanes")
        if (ln and len(ln) == 6
                and all(x.get("p") is not None and x.get("q") for x in ln)):
            out[(r.get("jcd"), r.get("rno"))] = {"lanes": ln, "top": r.get("top")}
    for src in ("picks", "ana"):
        for r in day.get(src) or []:
            k = (r.get("jcd"), r.get("rno"))
            if k in out and not out[k]["top"] and r.get("top"):
                out[k]["top"] = r["top"]
    return out


def empty_side():
    return {"cal": [[0, 0, 0.0] for _ in BANDS[:-1]],
            "fav": [[0, 0, 0.0] for _ in range(len(JUDGE))], "ll": 0.0}


def summarize(day, res):
    """1日ぶん。res は (jcd,rno) -> (確定した組, 払戻)。結果の無いレースは数えない"""
    st = {"n": 0, "p": empty_side(), "q": empty_side(), "t8": [0, 0, 0.0], "t1": [0, 0]}
    for k, r in races_of(day).items():
        got = res.get(k)
        if not got or not got[0]:
            continue
        combo = got[0]
        try:
            first = int(combo.split("-")[0])
        except (ValueError, IndexError):
            continue
        lanes = sorted(r["lanes"], key=lambda x: x["lane"])
        st["n"] += 1
        for side in ("p", "q"):
            pr = [float(x[side]) for x in lanes]
            tot = sum(pr) or 1.0
            pr = [v / tot for v in pr]
            s = st[side]
            for x, v in zip(lanes, pr):
                b = s["cal"][band(v, BANDS)]
                b[0] += 1
                b[1] += int(x["lane"] == first)
                b[2] += v
            i = max(range(6), key=lambda j: pr[j])
            won = int(lanes[i]["lane"] == first)
            for j in (0, 1 + band(pr[i], JUDGE)):
                s["fav"][j][0] += 1
                s["fav"][j][1] += won
                s["fav"][j][2] += pr[i]
            pw = pr[[x["lane"] for x in lanes].index(first)]
            s["ll"] += -math.log(max(pw, 1e-12))
        top = r.get("top") or []
        if len(top) >= 8:
            st["t8"][0] += 1
            st["t8"][1] += int(any(t[0] == combo for t in top[:8]))
            st["t8"][2] += sum(float(t[1]) for t in top[:8])
            st["t1"][0] += 1
            st["t1"][1] += int(top[0][0] == combo)
    for side in ("p", "q"):
        s = st[side]
        s["ll"] = round(s["ll"], 4)
        for row in s["cal"] + s["fav"]:
            row[2] = round(row[2], 4)
    st["t8"][2] = round(st["t8"][2], 4)
    return st


def load_out(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("version") == VERSION:
            return d
    except (OSError, ValueError):
        pass
    return {"version": VERSION, "bands": BANDS, "judge": JUDGE, "days": {}}


def update(out, days, kdir, log=print):
    """days（history.json の days）のうち、集計できる日を out に入れる。書き換えた日数を返す"""
    changed = 0
    for day in days:
        date = day.get("date")
        if not date or not races_of(day):
            continue
        res = S.kmap(kdir, date)
        if not res:
            continue                      # Kファイルがまだ。次の回に持ち越す
        st = summarize(day, res)
        old = out["days"].get(date)
        if st["n"] and (old is None or st["n"] > old.get("n", 0)):
            out["days"][date] = st
            changed += 1
            log(f"  {date}: {st['n']}レース")
    return changed


def save_out(out, path):
    out["updated"] = datetime.now(JST).isoformat(timespec="seconds")
    out["days"] = dict(sorted(out["days"].items()))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def backfill_days(since):
    """git の履歴から、since 以降の各日の内訳を拾う。日ごとに一番レースの多い版を返す。

    ★内訳は14日で消えるので、その日から14日以内の history.json なら残っている。
      1日1つ（その日最後のコミット）だけ読めば足りる。
    """
    log = subprocess.run(["git", "log", "--format=%H %cd", "--date=format:%Y%m%d",
                          f"--since={since[:4]}-{since[4:6]}-{since[6:]}", "--", SITE],
                         capture_output=True, text=True, check=True).stdout
    last = {}
    for line in log.splitlines():
        sha, d = line.split()
        last.setdefault(d, sha)          # 新しい順なので最初がその日の最後
    best = {}
    for d, sha in sorted(last.items()):
        blob = subprocess.run(["git", "show", f"{sha}:{SITE}"], capture_output=True,
                              text=True, encoding="utf-8").stdout
        try:
            h = json.loads(blob)
        except ValueError:
            continue
        for day in h.get("days") or []:
            if (day.get("date") or "") < since:
                continue
            n = len(races_of(day))
            if n and n > best.get(day["date"], (0, None))[0]:
                best[day["date"]] = (n, day)
        print(f"  {d} の版を読みました（{sha[:8]}）", flush=True)
    return [day for _, day in (best[k] for k in sorted(best))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kfile", default="../v22/kfile")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--backfill", metavar="YYYYMMDD", default=None,
                    help="この日以降を git の履歴から作り直す")
    args = ap.parse_args()

    out = load_out(args.out)
    if args.backfill:
        days = backfill_days(args.backfill)
    else:
        try:
            with open(SITE, encoding="utf-8") as f:
                days = json.load(f).get("days") or []
        except (OSError, ValueError):
            print(f"{SITE} がありません")
            return 0
    n = update(out, days, args.kfile)
    if n:
        save_out(out, args.out)
    tot = sum(d["n"] for d in out["days"].values())
    print(f"予想の精度: {n}日ぶん更新 / 合計 {len(out['days'])}日 {tot:,}レース")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
