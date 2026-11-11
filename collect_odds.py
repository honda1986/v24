#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_odds.py -- 3連単以外の賭式の確定オッズを1日1ファイルで貯める（band_howto.md §30）

  oddsx/YYYYMMDD.json.gz
  {"date":"20261110",
   "races":[{"jcd":22,"rno":12,
             "win":[6], "place":[[下限,上限] x6],          艇番の順
             "2t":[30], "2f":[15], "3f":[20], "k":[[下限,上限] x15]}, ...]}
  並びは oddsx.PAIRS / PAIRS2 / TRIOS。3連単の確定オッズは v22 の raw にある。

★判定時の値は yosou.py が snap/ に残す（"x" の行）。こちらは締切後の確定値。
  淡水の9場は v24 が買わないので取らない（1日の取得を半分にするため）。

使い方（runner.py motor が翌朝に呼ぶ）
  python collect_odds.py --date 20261110
"""
import argparse
import gzip
import json
import os
import time
from datetime import datetime

import official as OF
import oddsx as OX
import select_rule as SR

OUTDIR = "oddsx"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--gap", type=float, default=0.3, help="1リクエストの間隔(秒)")
    args = ap.parse_args()
    date = args.date or datetime.now(OF.JST).strftime("%Y%m%d")
    path = f"{OUTDIR}/{date}.json.gz"
    if os.path.exists(path):
        print(f"{path} は既にあります")
        return

    races, miss = [], 0
    for jcd in range(1, 25):
        if jcd in SR.TANSUI:
            continue
        sched, _ = OF.fetch_close(date, jcd)
        time.sleep(args.gap)
        if not sched:
            continue
        print(f"  {jcd:02d}場", flush=True)
        for rno in range(1, 13):
            x = OX.fetch(date, jcd, rno, gap=args.gap)
            time.sleep(args.gap)
            if not x or not x.get("win"):
                miss += 1
                continue
            races.append({"jcd": jcd, "rno": rno, **x})
    if not races:
        print("取れませんでした")
        return
    os.makedirs(OUTDIR, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump({"date": date, "races": races}, f, ensure_ascii=False, separators=(",", ":"))
    full = sum(1 for r in races if all(r.get(k) for k in ("win", "place", "2t", "2f", "3f", "k")))
    print(f"保存 {path}  {len(races)}レース（6賭式そろい {full}） / 取れず {miss}")


if __name__ == "__main__":
    main()
