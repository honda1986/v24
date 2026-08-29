#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prefetch.py -- 朝のうちに当日ぶんの出走表を取って cache に入れておく

★なぜ要るのか
  info.kyotei.fun は GitHub Actions から時々まったく届かない（実測）。
  締切4〜30分前という短い窓でそれに当たると、そのレースは諦めるしかない。
  出走表の数値は日中変わらないので、朝に取っておけば窓の中で取りに行かずに済む。

  取れなかったぶんは本番の窓でその都度取りにいく（従来どおり）。何度回しても
  cache にあるものは飛ばすので、時間をおいて2回3回と回せば埋まっていく。

  python prefetch.py
"""
import argparse
import time
from datetime import datetime

import official as OF
import select_rule as SR
import yosou as Y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--gap", type=float, default=0.4)
    args = ap.parse_args()
    date = args.date or datetime.now(OF.JST).strftime("%Y%m%d")

    targets = [j for j in Y.VENUE if j not in SR.TANSUI]
    Y.prune(date)
    sched = Y.close_times(date, targets)
    print(f"{date}  開催は {len(sched)}場（淡水{len(SR.TANSUI)}場は除外）")

    got = have = ng = 0
    for jcd in sorted(sched):
        n_ok = 0
        for rno in range(1, 13):
            path = f"{Y.CACHE_DIR}/rc_{date}_{jcd:02d}_{rno}.json"
            c = Y._load(path)
            if c and len(c) == 6:
                have += 1
                n_ok += 1
                continue
            rc = Y.racecard(date, jcd, rno)
            time.sleep(args.gap)
            if rc and len(rc) == 6:
                got += 1
                n_ok += 1
            else:
                ng += 1
        print(f"  {Y.VENUE.get(jcd, jcd):<4} {n_ok:>2}/12", flush=True)

    print(f"\n新たに取得 {got} / すでにあった {have} / 取れず {ng}")
    if ng:
        print("★ 取れなかったぶんは、時間をおいてもう一度このスクリプトを回すか、")
        print("  本番の窓で取り直しになります（そのとき届かなければそのレースは見送り）")


if __name__ == "__main__":
    main()
