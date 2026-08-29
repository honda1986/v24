#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""oddscheck.py -- オッズの並び順が正しいかを、過去の払戻金で検算する

★これを通すまで本番に金を入れてはいけない。

3連単の払戻金 = 確定オッズ × 100円。Kファイルには的中組(hit)と払戻(pay_3t)が
入っているので、公式から取ったオッズ120点のうち「的中組の位置」の値が
払戻/100 と一致するかを見れば、並び順が正しいかどうかが一意に決まる。

  1/オッズの合計が 1.337 になることは、並び順の検証にならない。
  合計は順番を入れ替えても変わらないため。ここを混同しないこと。

  python oddscheck.py --kfile ../v22/kfile --days 3 --per-day 8
"""
import argparse
import datetime
import gzip
import json
import os

import official as OF
from features import COMBOS, CIX

JST = datetime.timezone(datetime.timedelta(hours=9))


def kraces(kdir, date):
    p = f"{kdir}/{date}.json.gz"
    if not os.path.exists(p):
        return []
    out = []
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for r in json.load(f).get("races") or []:
            h, pay = r.get("hit"), r.get("pay_3t")
            if h in CIX and pay and pay > 0:
                out.append((r["jcd"], r["rno"], h, float(pay)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kfile", default="../v22/kfile")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--per-day", type=int, default=8)
    args = ap.parse_args()

    today = datetime.datetime.now(JST).date()
    ok = ng = miss = 0
    worst = []
    for i in range(1, args.days + 1):
        date = (today - datetime.timedelta(days=i)).strftime("%Y%m%d")
        rs = kraces(args.kfile, date)
        if not rs:
            print(f"  {date} Kファイルがありません")
            continue
        step = max(1, len(rs) // args.per_day)
        pick = rs[::step][:args.per_day]
        print(f"\n{date}  {len(pick)}レースを検算")
        for jcd, rno, hit, pay in pick:
            o = OF.fetch_odds(date, jcd, rno, tries=2, verbose=False)
            if not o:
                miss += 1
                print(f"  −  {jcd:02d}場 {rno:>2}R  オッズが取れない")
                continue
            got = o[CIX[hit]] * 100.0
            rel = abs(got - pay) / pay
            if rel <= 0.02:                     # 端数・更新遅れの許容
                ok += 1
                print(f"  ○  {jcd:02d}場 {rno:>2}R  {hit}  "
                      f"払戻{pay:>8,.0f}円  オッズから{got:>8,.0f}円")
            else:
                ng += 1
                # 払戻と一致する組がどこにあるかを探す（並び順のずれ方が分かる）
                cand = [COMBOS[k] for k, v in enumerate(o)
                        if abs(v * 100 - pay) / pay <= 0.02]
                worst.append((jcd, rno, hit, pay, got, cand[:3]))
                print(f"  ✗  {jcd:02d}場 {rno:>2}R  {hit}  "
                      f"払戻{pay:>8,.0f}円  オッズから{got:>8,.0f}円"
                      f"   その払戻に合う組 {cand[:3]}")

    n = ok + ng
    print(f"\n=== 一致 {ok} / 不一致 {ng} / 取れず {miss} ===")
    if n and ok == n:
        print("★ 並び順は正しい。オッズをそのまま信用してよい")
    elif ng:
        print("★ 並び順が違う。このまま動かすと、間違った組を買い続ける。")
        print("  『その払戻に合う組』が実際の組とどうずれているかを見れば、")
        print("  _place() の割り当て（2着=others[r//4] / 3着=…[r%4]）を直せる。")
        for jcd, rno, hit, pay, got, cand in worst[:5]:
            print(f"    {jcd:02d}場{rno}R  本当は {hit} なのに、その値は {cand} にある")
    else:
        print("★ 検算できていない。日付を変えて試すこと")


if __name__ == "__main__":
    main()
