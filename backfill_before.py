#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backfill_before.py -- 過去の直前情報をさかのぼって before_hist/ に貯める（band_howto.md §30）

公式の直前情報ページは過去のレースも残っている（2023/06 まで確かめた）。チルト・部品交換・
調整重量・前走に加えて、展示進入・展示ST・展示タイム・気象も同じページにあるので、
before/（2026-09-23〜）より前の分もそろえられる。

  python backfill_before.py --from 20230501 --to 20261110 --shard 0 --shards 8 --raw v22src/raw

  ・レースの一覧は v22 の raw から作る（一覧のためのリクエストは要らない）。淡水は取らない
  ・日付を shards 個に振り分ける（k 番目の日 → k % shards）。さらに1本の中でも8ページ同時に取る
    （公式は GitHub から1ページ8〜10秒かかるが、同時に取っても1件あたりは遅くならない）
  ・1日1ファイル before_hist/YYYYMMDD.json.gz。既にある日は飛ばす（やり直しても同じ）
  ・--every 日ぶんごとに commit して push（main。PC や予備運転とは別のフォルダ）
★before_hist/ は runner.py の DATA_DIRS に入れない。PC の取り込みは「手元優先」なので、
  入れると PC が古い写しで上書きしうる。ここだけが書き、新しいファイルを足すだけにする。
"""
import argparse
import glob
import gzip
import json
import os
import random
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import beforeinfo as BI
import collect_before as CB
import select_rule as SR

OUTDIR = "before_hist"


def races_of(raw_dir, date):
    """v22 raw にあるその日のレース（淡水を除く）"""
    p = f"{raw_dir}/{date}.json.gz"
    if not os.path.exists(p):
        return []
    with gzip.open(p, "rt", encoding="utf-8") as f:
        rd = json.load(f)
    return sorted({(r["jcd"], r["rno"]) for r in rd.get("races") or []
                   if r.get("jcd") and r["jcd"] not in SR.TANSUI})


def one_day(date, races, gap, threads=1):
    """★公式は GitHub から1ページ 8〜10秒かかる（2026-11-11 実測）。ただし同時に取っても
    1件あたりは遅くならない（6本同時で 12件 20秒）。なので threads 本で並べる。
    beforeinfo のセッションは同時8本までなので、threads は 8 以下にすること"""
    def get(rc):
        jcd, rno = rc
        info = BI.fetch(date, jcd, rno, tries=1)
        time.sleep(gap)
        return jcd, rno, info
    with ThreadPoolExecutor(max(1, threads)) as ex:
        got = list(ex.map(get, races))
    out, miss = [], 0
    for jcd, rno, info in got:
        if not info or not info.get("tenji"):
            miss += 1
            continue
        out.append(CB.record(jcd, rno, info))
    return out, miss


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True)


def push(message):
    """新しいファイルを足すだけなので、取り込み直して載せれば必ず通る。何度か試す"""
    git("add", OUTDIR)
    if git("diff", "--cached", "--quiet").returncode == 0:
        return True
    git("commit", "-q", "-m", message)
    for i in range(8):
        if git("pull", "-q", "--rebase", "origin", "main").returncode == 0 \
                and git("push", "-q", "origin", "HEAD:main").returncode == 0:
            return True
        git("rebase", "--abort")
        time.sleep(5 + random.random() * 10 * (i + 1))
    print("  ★push できず（次の回に持ち越し）")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default="20230501")
    ap.add_argument("--to", default="20261110")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--raw", default="../v22/raw")
    ap.add_argument("--gap", type=float, default=0.5, help="1リクエストの間隔(秒)")
    ap.add_argument("--every", type=int, default=5, help="この日数ごとに push")
    ap.add_argument("--threads", type=int, default=8, help="同時に取る本数（8 まで）")
    ap.add_argument("--budget", type=int, default=19800, help="この秒数で切り上げる")
    ap.add_argument("--no-push", dest="do_push", action="store_false", default=True)
    args = ap.parse_args()
    t0 = time.time()
    days = sorted(os.path.basename(p)[:8] for p in glob.glob(f"{args.raw}/*.json.gz"))
    days = [d for k, d in enumerate(d for d in days if args.frm <= d <= args.to)
            if k % args.shards == args.shard]
    todo = [d for d in days if not os.path.exists(f"{OUTDIR}/{d}.json.gz")]
    print(f"担当 {len(days)}日 / まだ {len(todo)}日（shard {args.shard}/{args.shards}）", flush=True)
    os.makedirs(OUTDIR, exist_ok=True)
    done = 0
    for d in todo:
        if time.time() - t0 > args.budget:
            print("持ち時間を使い切ったので、残りは次の回へ")
            break
        races = races_of(args.raw, d)
        if not races:
            continue
        out, miss = one_day(d, races, args.gap, min(args.threads, 8))
        if out:
            with gzip.open(f"{OUTDIR}/{d}.json.gz", "wt", encoding="utf-8") as f:
                json.dump({"date": d, "races": out}, f, ensure_ascii=False, separators=(",", ":"))
        done += 1
        print(f"  {d}  {len(out)}レース（取れず {miss}）  {time.time()-t0:.0f}秒", flush=True)
        if args.do_push and done % args.every == 0:
            push(f"before_hist: shard {args.shard} {d}")
    if args.do_push:
        push(f"before_hist: shard {args.shard} 終わり")
    left = sum(1 for d in days if not os.path.exists(f"{OUTDIR}/{d}.json.gz"))
    print(f"この回 {done}日 / 残り {left}日")


if __name__ == "__main__":
    main()
