#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""snap_pack.py -- yosou.py が貯めた判定時オッズを1日1ファイルにまとめる

  snap/YYYYMMDD.jsonl（git に入れない。yosou.py が3分おきに1行ずつ足す）
    → odds_snap/YYYYMMDD.json.gz（git に入れる）
  {"date":"20260926",
   "rows":[{"t":"10:41:07","jcd":24,"rno":5,"left":7,"odds":[120個]}, ...]}

★band_howto.md §15 の続き。本番は締切2〜15分前のオッズで判定し、
  バックテストは確定オッズで判定している。その差（目減り）を、
  買った組だけでなく見たレース全部で測るための記録。
  確定オッズは v22/raw にある。

使い方（runner.py motor が翌朝に呼ぶ）
  python snap_pack.py --date 20260926
  python snap_pack.py                    # 今日より前でまだまとめていない日を全部
"""
import argparse
import glob
import gzip
import json
import os
from datetime import datetime

import official as OF

SRC, OUT = "snap", "odds_snap"


def pack(date):
    src, out = f"{SRC}/{date}.jsonl", f"{OUT}/{date}.json.gz"
    if not os.path.exists(src):
        return f"{date}: 記録なし"
    rows, bad = [], 0
    with open(src, encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except ValueError:
                bad += 1              # 書きかけで落ちた行。捨てる
    if os.path.exists(out):
        # ★既にあれば足し合わせる（同じ日を2回まとめても消えない）
        with gzip.open(out, "rt", encoding="utf-8") as f:
            old = json.load(f).get("rows") or []
        seen = {(r["t"], r["jcd"], r["rno"]) for r in old}
        rows = old + [r for r in rows if (r["t"], r["jcd"], r["rno"]) not in seen]
    rows.sort(key=lambda r: (r["jcd"], r["rno"], r["t"]))
    os.makedirs(OUT, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump({"date": date, "rows": rows}, f, separators=(",", ":"))
    os.remove(src)
    nr = len({(r["jcd"], r["rno"]) for r in rows})
    return f"{date}: {len(rows)}回ぶん / {nr}レース → {out}" + (f"（壊れた行 {bad}）" if bad else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    today = datetime.now(OF.JST).strftime("%Y%m%d")
    if args.date:
        dates = [args.date]
    else:
        # ★今日のぶんはまだ yosou が書き足しているので触らない
        dates = sorted(os.path.basename(p)[:8] for p in glob.glob(f"{SRC}/*.jsonl"))
        dates = [d for d in dates if d < today]
    if not dates:
        print("まとめる日はありません")
    for d in dates:
        print(pack(d))


if __name__ == "__main__":
    main()
