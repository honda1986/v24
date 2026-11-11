#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_raw.py -- v22 の raw / tokuten と同じ形のデータを公式から作る（raw24/ tokuten24/、band_howto.md §31）

★v22 の raw は 2026-10-20 から毎日0レース、tokuten は 10/19 で止まった（info.kyotei.fun に
  GitHub から届かない）。v24 の検証（bt.py / bt_snap.py / train.py）と settle が困るので、
  v24 が自分で作る。v22 にその日のデータがあれば作らない（--all で作る。突き合わせ用）。

  raw24/YYYYMMDD.json.gz   v22 raw と同じ形 {"date","combos","races":[{jcd,rno,entries[6],weather,odds[120],hit,pay_3t}]}
    entries の出走表の数値 … 公式の出走表（officialcard）
    tenji / course_in / rank … Kファイル（展示タイム・進入・着順）
    odds … 公式の確定3連単オッズ / hit・pay_3t … Kファイル
  tokuten24/YYYYMMDD.json.gz  v22 tokuten と同じ形 {"date","venues":{jcd: 今節のページ}}（uchisankaku）

  python collect_raw.py --date 20261110 --kfile ../v22/kfile
  python collect_raw.py --from 20261020 --to 20261110 --shard 0 --shards 10 --kfile v22src/kfile --raw v22src/raw
"""
import argparse
import glob
import gzip
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import features as F
import official as OF
import officialcard as OC
import rawsrc as RS
import tokuten as TK

CARD = ("cls_val", "age", "weight", "f_count", "avg_st", "n_win", "n_2ren",
        "l_win", "l_2ren", "m_2ren", "b_2ren")


def kraces(kfile_dir, date):
    p = f"{kfile_dir}/{date}.json.gz"
    if not os.path.exists(p):
        return []
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return [r for r in json.load(f).get("races") or [] if r.get("hit")]


def _rank(chaku):
    try:
        return int(str(chaku))
    except (TypeError, ValueError):
        return None                     # F / L / 欠 / 失 など


def build_race(date, k, card, odds):
    """Kファイルの1レース + 公式の出走表 + 確定オッズ → v22 raw の1レース。足りなければ None"""
    if not card or len(card) != 6 or not odds or len(odds) != 120:
        return None
    ke = {e["lane"]: e for e in k.get("entries") or []}
    entries = []
    for c in sorted(card, key=lambda z: z["lane"]):
        e = ke.get(c["lane"], {})
        entries.append({"lane": c["lane"], **{f: c.get(f) for f in CARD},
                        "tenji": e.get("tenji"), "course_in": e.get("course"),
                        "rank": _rank(e.get("chaku")), "toban": c.get("toban") or e.get("toban")})
    return {"date": date, "jcd": k["jcd"], "rno": k["rno"], "entries": entries,
            "weather": {"temp": None, "wind": k.get("wind"), "wave": k.get("wave"), "water_temp": None},
            "odds": [float(o) for o in odds], "n_odds": 120, "hit": k["hit"],
            "pay_3t": k.get("pay_3t"), "src": "official"}


def raw_day(date, kfile_dir, threads=8, gap=0.3):
    ks = kraces(kfile_dir, date)

    def one(k):
        card = OC.fetch_card(date, k["jcd"], k["rno"])
        time.sleep(gap)
        odds = OF.fetch_odds(date, k["jcd"], k["rno"], verbose=False)
        time.sleep(gap)
        return build_race(date, k, card, odds)
    with ThreadPoolExecutor(max(1, min(threads, 8))) as ex:       # 公式のセッションは同時8本まで
        got = list(ex.map(one, ks))
    races = [r for r in got if r]
    return {"date": date, "combos": F.COMBOS, "races": races}, len(ks) - len(races)


def tokuten_day(date, jcds):
    sess = TK.make_session()
    venues = {}
    for jcd in sorted(jcds):
        html = TK.fetch(sess, jcd, date)
        page = TK.parse_page(html, date) if html else None
        if page and page.get("races"):
            venues[str(jcd)] = page
        time.sleep(0.5)
    return {"date": date, "venues": venues}


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def one_date(date, args):
    """その日の raw24 と tokuten24 を作る（v22 にあれば作らない）。作ったものを返す"""
    did = []
    rp, tp = f"{RS.RAW24}/{date}.json.gz", f"{RS.TOK24}/{date}.json.gz"
    v22 = RS.load_raw(args.raw, date, raw24=None) if args.raw else {"races": []}
    if not os.path.exists(rp) and (args.all or not v22.get("races")):
        rd, miss = raw_day(date, args.kfile, args.threads)
        if rd["races"]:
            save(rp, rd)
            did.append(f"raw24 {len(rd['races'])}レース（取れず {miss}）")
    have_tok = args.tokuten and os.path.exists(f"{args.tokuten}/{date}.json.gz")
    if not os.path.exists(tp) and (args.all or not have_tok):
        jcds = {k["jcd"] for k in kraces(args.kfile, date)}
        if jcds:
            td = tokuten_day(date, jcds)
            if td["venues"]:
                save(tp, td)
                did.append(f"tokuten24 {len(td['venues'])}場")
    return did


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--from", dest="frm", default=None)
    ap.add_argument("--to", default=None)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--kfile", default="../v22/kfile")
    ap.add_argument("--raw", default="../v22/raw", help="v22 の raw（その日があれば作らない）")
    ap.add_argument("--tokuten", default="../v22/tokuten")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--all", action="store_true", help="v22 にあっても作る（突き合わせ用）")
    ap.add_argument("--budget", type=int, default=0, help="この秒数で切り上げる（0 は無制限）")
    ap.add_argument("--push-every", type=int, default=0, help="この日数ごとに push（backfill_before と同じ）")
    args = ap.parse_args()
    if args.date:
        days = [args.date]
    else:
        days = sorted(os.path.basename(p)[:8] for p in glob.glob(f"{args.kfile}/*.json.gz"))
        days = [d for k, d in enumerate(x for x in days if args.frm <= x <= args.to)
                if k % args.shards == args.shard]
    t0, n = time.time(), 0
    for d in days:
        if args.budget and time.time() - t0 > args.budget:
            print("持ち時間を使い切ったので、残りは次の回へ")
            break
        did = one_date(d, args)
        if did:
            n += 1
            print(f"  {d}  " + " / ".join(did) + f"  {time.time()-t0:.0f}秒", flush=True)
            if args.push_every and n % args.push_every == 0:
                import backfill_before as BB
                BB.push(f"raw24: shard {args.shard} {d}", paths=("raw24", "tokuten24"))
    if args.push_every:
        import backfill_before as BB
        BB.push(f"raw24: shard {args.shard} 終わり", paths=("raw24", "tokuten24"))
    print(f"作った日 {n}")


if __name__ == "__main__":
    main()
