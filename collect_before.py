#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_before.py -- 直前情報を1日1ファイルで貯める

引き継ぎメモ §7-1 の宿題。fetch_beforeinfo() は前から動いていたのに保存していなかった。
展示ST・展示進入・チルト相当の情報は、貯め始めないと永久に検証できない。

  before/YYYYMMDD.json.gz
  {"date":"20260822",
   "races":[{"jcd":24,"rno":1,
             "tenji":{"1":6.61,...}, "course_in":{"1":1,...},
             "exhibition_st":{"1":".15",...}, "weight":{...},
             "weather":{"風速":2.0,"気温":30.0,"水温":28.0,"波高":1.0}}, ...]}

使い方
  python collect_before.py              # 今日ぶんを取る(レース後でよい)
  python collect_before.py --date 20260821
"""
import argparse
import gzip
import json
import os
import time
from datetime import datetime

import beforeinfo as BI
import official as OF

OUTDIR = "before"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--gap", type=float, default=0.5, help="1リクエストの間隔(秒)")
    args = ap.parse_args()
    date = args.date or datetime.now(OF.JST).strftime("%Y%m%d")
    path = f"{OUTDIR}/{date}.json.gz"
    if os.path.exists(path):
        print(f"{path} は既にあります")
        return

    races, miss = [], 0
    for jcd in range(1, 25):
        sched, _ = OF.fetch_close(date, jcd)
        time.sleep(args.gap)
        if not sched:
            continue
        print(f"  {jcd:02d}場 12レース", flush=True)
        for rno in range(1, 13):
            info = BI.fetch(date, jcd, rno, tries=1)
            time.sleep(args.gap)
            if not info or not info.get("tenji"):
                miss += 1
                continue
            races.append({"jcd": jcd, "rno": rno,
                          "tenji": {str(k): v for k, v in info["tenji"].items()},
                          "course_in": {str(k): v for k, v in info["course_in"].items()},
                          "exhibition_st": {str(k): v for k, v
                                            in info["exhibition_st"].items()},
                          "weight": {str(k): v for k, v in info["weight"].items()},
                          "weather": info["weather"]})
    if not races:
        print("取れませんでした")
        return
    os.makedirs(OUTDIR, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump({"date": date, "races": races}, f, ensure_ascii=False)
    nst = sum(1 for r in races if r["exhibition_st"])
    nco = sum(1 for r in races if len(r["course_in"]) == 6)
    print(f"保存 {path}  {len(races)}レース"
          f"  展示ST {nst}件 / 展示進入(6艇そろい) {nco}件 / 取れず {miss}件")


if __name__ == "__main__":
    main()
