#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""settle.py -- 買った記録に結果と「オッズの目減り」を入れる（予想サイト用）

history.json の picks は、通知した時点では結果が空。翌日 Kファイルが出たら
的中したか・払戻がいくらかを入れる。motor.yml が毎朝 v22 の kfile を
持ってくるので、そのついでに走らせる。

  python settle.py --kfile /tmp/v22/kfile

★紙で回している間の唯一の答え合わせなので、ここが狂うと何も分からなくなる。
  だから「Kファイルにそのレースが無い」場合は空のままにして、
  勝手に不的中扱いにはしない。

★もうひとつの仕事：オッズの目減りを測る（2026-09-03 追加）
  バックテストの95.3%は「確定オッズ」で測った値。実際は締切前のオッズを見て
  買うので、そこから動く。どれだけ目減りするかは今まで誰も測っていなかった。
  v22 の raw に確定オッズ120通りが翌朝そろうので、通知時に記録したオッズと
  突き合わせる。
  ・raw のオッズが確定値であることは実測で確認済み（4,558レース、98.0%が
    Kファイルの払戻と完全一致）
  ・買った組が「確定オッズでも p/q>1.05 を満たしたか」も併せて数える。
    満たさなくなっていたら、それは選別そのものが幻だったということ
"""
import argparse
import glob
import gzip
import io
import json
import os
import urllib.error
import urllib.request

SITE = "history.json"
BET_YEN = 100
PQ_MIN = 1.05          # select_rule と同じ。確定オッズでも満たすか数えるため
RAW_URL = "https://raw.githubusercontent.com/honda1986/v22/main/raw/{}.json.gz"

COMBOS = [f"{a}-{b}-{c}" for a in range(1, 7) for b in range(1, 7) if b != a
          for c in range(1, 7) if c not in (a, b)]
CIX = {c: i for i, c in enumerate(COMBOS)}


def kmap(kdir, date):
    p = f"{kdir}/{date}.json.gz"
    if not os.path.exists(p):
        return None
    out = {}
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for r in json.load(f).get("races") or []:
            if r.get("hit"):
                out[(r["jcd"], r["rno"])] = (r["hit"], float(r.get("pay_3t") or 0))
    return out


def rawmap(rawdir, date):
    """その日の確定オッズ。(jcd,rno) -> 120個のリスト。取れなければ None。

    ★手元に無ければ v22 リポジトリから1日ぶん(70KB程度)だけ取る。
      raw を丸ごと checkout すると60MB超になるので、それは避ける。
    """
    blob = None
    p = f"{rawdir}/{date}.json.gz"
    if os.path.exists(p):
        blob = open(p, "rb").read()
    else:
        try:
            with urllib.request.urlopen(RAW_URL.format(date), timeout=30) as r:
                blob = r.read()
        except (urllib.error.URLError, OSError, ValueError):
            return None
    try:
        with gzip.open(io.BytesIO(blob), "rt", encoding="utf-8") as f:
            rd = json.load(f)
    except (OSError, ValueError):
        return None
    out = {}
    for r in rd.get("races") or []:
        od = r.get("odds")
        if od and len(od) == 120 and all(x and x > 0 for x in od):
            out[(r["jcd"], r["rno"])] = od
    return out or None


def drift(pick, odds120):
    """通知時オッズ → 確定オッズ を、買った組ごとに書き込む。

    確定オッズから市場確率 q を作り直し、p/q がまだ基準を超えているかも見る。
    """
    inv = [1.0 / o for o in odds120]
    tot = sum(inv)
    kept = 0
    for b in pick.get("buys") or []:
        i = CIX.get(b["combo"])
        if i is None:
            continue
        fo = float(odds120[i])
        fq = inv[i] / tot
        b["fodds"] = round(fo, 1)
        b["fq"] = round(fq, 5)
        b["fpq"] = round(float(b["p"]) / fq, 3) if fq > 0 else None
        b["move"] = round(fo / float(b["odds"]), 3) if b.get("odds") else None
        if b["fpq"] is not None and b["fpq"] > PQ_MIN:
            kept += 1
    pick["kept"] = kept
    return kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kfile", default="../v22/kfile")
    ap.add_argument("--raw", default="../v22/raw")
    args = ap.parse_args()

    try:
        with open(SITE, encoding="utf-8") as f:
            h = json.load(f)
    except (OSError, ValueError):
        print(f"{SITE} がありません。まだ1件も通知が出ていません")
        return

    filled = waiting = 0
    for day in h.get("days") or []:
        pend = [p for p in day.get("picks") or [] if p.get("hit") is None]
        # 目減りだけまだ入っていないレースも拾う（結果が先に入った場合）
        nod = [p for p in day.get("picks") or []
               if any("fodds" not in b for b in (p.get("buys") or []))]
        if nod:
            rm = rawmap(args.raw, day["date"])
            if rm:
                for p in nod:
                    od = rm.get((p["jcd"], p["rno"]))
                    if od:
                        drift(p, od)
        if not pend:
            continue
        km = kmap(args.kfile, day["date"])
        if km is None:
            waiting += len(pend)
            print(f"  {day['date']} Kファイルがまだありません（{len(pend)}件は結果待ち）")
            continue
        for p in pend:
            got = km.get((p["jcd"], p["rno"]))
            if not got:
                waiting += 1
                continue
            combo, pay = got
            won = [b for b in p["buys"] if b["combo"] == combo]
            p["combo"] = combo
            p["pay"] = pay
            p["hit"] = bool(won)
            # 1点100円なので、払戻は「オッズ×100」＝ pay をそのまま受け取る
            p["ret"] = pay if won else 0.0
            filled += 1

    with open(SITE, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False)

    # 通しの成績を出す
    picks = [p for d in (h.get("days") or []) for p in (d.get("picks") or [])]
    done = [p for p in picks if p.get("hit") is not None]
    cost = sum(p.get("cost") or 0 for p in done)
    ret = sum(p.get("ret") or 0 for p in done)
    print(f"\n結果を入れた {filled}件 / 結果待ち {waiting}件")
    if done:
        print(f"確定 {len(done)}レース  的中 {sum(1 for p in done if p['hit'])}  "
              f"回収率 {ret/cost*100:.1f}%  収支 {ret-cost:+,.0f}円")
        print("★60レースを超えるまでは、ほぼ運の範囲。数字が動いても慌てないこと")
    else:
        print("まだ確定したレースがありません")

    # --- オッズの目減り ---
    mv = [b["move"] for p in picks for b in (p.get("buys") or [])
          if b.get("move")]
    if mv:
        mv.sort()
        n = len(mv)
        avg = sum(mv) / n
        med = mv[n // 2]
        dn = sum(1 for x in mv if x < 1.0) / n * 100
        kept = sum(p.get("kept") or 0 for p in picks if p.get("kept") is not None)
        tot = sum(len(p.get("buys") or []) for p in picks
                  if p.get("kept") is not None)
        print(f"\nオッズの目減り（買った {n}組）")
        print(f"  通知時 → 確定   平均 {avg:.3f}倍  中央 {med:.3f}倍  "
              f"下がった {dn:.0f}%")
        if tot:
            print(f"  確定オッズでも p/q>{PQ_MIN} を満たしたまま  "
                  f"{kept}/{tot}（{kept/tot*100:.0f}%）")
        print(f"  ★素朴な見積りでは回収率 {(avg-1)*100:+.1f}pt。"
              "ただし当たりやすさとの相関を無視した値なので、")
        print("    確定した実測の回収率が出るまでは目安に留めること")
    else:
        print("\n（確定オッズがまだ引けていないので、目減りは測れていません）")


if __name__ == "__main__":
    main()
