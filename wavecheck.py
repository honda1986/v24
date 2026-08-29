#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wavecheck.py -- 波高・風速だけを並列で集めて、Kファイルと突き合わせる

collect_before.py は全部（展示タイム・展示ST・展示進入・体重・気象）を
24場×12レース、1件ずつ0.5秒あけて取るので1日あたり5分以上かかる。
この確認に要るのは気象2項目だけなので、無駄を全部落とす。

  ・淡水9場は最初から見ない（ルールの対象外）
  ・1場につき数レースだけ抜き取る（気象は日内でゆっくりしか動かない）
  ・数本を同時に取る

  python wavecheck.py --days 10

集めたものは wave/YYYYMMDD.json に残るので、途中で切れても続きから進む。
展示ST・展示進入の本格的なアーカイブは collect_before.py の役目で、そちらは別。
"""
import argparse
import concurrent.futures as cf
import datetime
import glob
import gzip
import json
import os
import threading
from collections import Counter

import beforeinfo as BI
import select_rule as SR

OUTDIR = "wave"
RACES = (1, 3, 5, 7, 9, 11)          # 1場あたりこの6レースだけ見る
JST = datetime.timezone(datetime.timedelta(hours=9))
_lock = threading.Lock()


def one(date, jcd, rno):
    info = BI.fetch(date, jcd, rno, tries=1)
    w = (info or {}).get("weather") or {}
    if w.get("波高") is None or w.get("風速") is None:
        return None
    return {"jcd": jcd, "rno": rno, "wave": w["波高"], "wind": w["風速"]}


def collect(date, workers):
    path = f"{OUTDIR}/{date}.json"
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    jobs = [(date, j, r) for j in range(1, 25)
            if j not in SR.TANSUI for r in RACES]
    got = []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(lambda a: one(*a), jobs):
            if res:
                got.append(res)
    os.makedirs(OUTDIR, exist_ok=True)
    json.dump(got, open(path, "w", encoding="utf-8"))
    return got


def kfile_of(kdir, date):
    p = f"{kdir}/{date}.json.gz"
    if not os.path.exists(p):
        return None
    out = {}
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for r in json.load(f).get("races") or []:
            if r.get("wave") is not None and r.get("wind") is not None:
                out[(r["jcd"], r["rno"])] = (r["wave"], r["wind"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--kfile", default="../v22/kfile")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    today = datetime.datetime.now(JST).date()
    pairs = []
    for i in range(1, args.days + 1):     # 昨日からさかのぼる
        date = (today - datetime.timedelta(days=i)).strftime("%Y%m%d")
        k = kfile_of(args.kfile, date)
        if k is None:
            print(f"  {date} Kファイルがありません。とばします")
            continue
        b = collect(date, args.workers)
        n = 0
        for r in b:
            key = (r["jcd"], r["rno"])
            if key in k:
                pairs.append(((r["wave"], r["wind"]), k[key]))
                n += 1
        print(f"  {date} 直前{len(b)}件 → 突き合わせ {n}件", flush=True)

    # 既に collect_before.py で貯めたぶんも混ぜる
    for p in sorted(glob.glob("before/*.json.gz")):
        date = os.path.basename(p)[:8]
        k = kfile_of(args.kfile, date)
        if k is None:
            continue
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for r in json.load(f)["races"]:
                w = r.get("weather") or {}
                key = (r["jcd"], r["rno"])
                if key in k and w.get("波高") is not None and w.get("風速") is not None:
                    if r["jcd"] not in SR.TANSUI:
                        pairs.append(((w["波高"], w["風速"]), k[key]))

    if not pairs:
        raise SystemExit("★ 突き合わせられるレースがありません")
    print(f"\n突き合わせ {len(pairs):,}レース（非淡水のみ）")

    bias = {}
    for i, (nm, unit) in enumerate((("波高", "cm"), ("風速", "m"))):
        dd = Counter()
        for b, k in pairs:
            dd[int(round(float(b[i]) - float(k[i])))] += 1
        tot = sum(dd.values())
        mu = sum(d * c for d, c in dd.items()) / tot
        sd = (sum((d - mu) ** 2 * c for d, c in dd.items()) / tot) ** 0.5
        bias[nm] = (mu, sd / tot ** 0.5)
        print(f"\n{nm}  ぴったり一致 {dd[0]/tot*100:.1f}%   "
              f"平均のずれ {mu:+.2f}{unit} (±{2*sd/tot**0.5:.2f})")
        for d in sorted(dd):
            if dd[d] / tot < 0.005:
                continue
            print(f"    {d:+d}{unit:<2} {dd[d]/tot*100:5.1f}%  "
                  + "#" * int(dd[d] / tot * 50))

    tt = tf = ft = ff = 0
    for b, k in pairs:
        ob = float(b[0]) < SR.WAVE_MAX and float(b[1]) < SR.WIND_MAX
        ok = float(k[0]) < SR.WAVE_MAX and float(k[1]) < SR.WIND_MAX
        tt += ob and ok
        tf += ob and not ok
        ft += (not ob) and ok
        ff += (not ob) and (not ok)
    n = tt + tf + ft + ff
    print(f"\n=== 足切り（波{SR.WAVE_MAX}cm未満・風{SR.WIND_MAX}m未満）  {n:,}レース ===")
    print(f"  Kファイルでの通過率 {(tt+ft)/n*100:5.1f}%"
          f"   ← 直近120日の非淡水は 48.6%")
    print(f"  直前情報での通過率  {(tt+tf)/n*100:5.1f}%"
          f"   ← ここが大きく低いなら、本番は検証より狭いルールで動く")
    print(f"  両方とも買う           {tt:>6,} ({tt/n*100:5.1f}%)")
    print(f"  両方とも見送り         {ff:>6,} ({ff/n*100:5.1f}%)")
    print(f"  直前で買い / K で見送り  {tf:>6,} ({tf/n*100:5.1f}%)  検証外のレースを買う")
    print(f"  直前で見送り / K で買い  {ft:>6,} ({ft/n*100:5.1f}%)  買えるはずを逃す")
    agree = (tt + ff) / n * 100
    print(f"\n  判定の一致率 {agree:.1f}%")

    # ★判定は一致率ではなく「平均のずれ」で行う（メモ §13）
    #   偏り  → 本番は別のルールで動く。閾値を取り直す必要がある
    #   ばらつき → 薄まるだけ。取り直すと §3 の罠にはまる
    print("\n  判定の根拠は一致率ではなく平均のずれ:")
    bad = []
    for nm, (mu, se) in bias.items():
        u = "cm" if nm == "波高" else "m"
        if abs(mu) > max(0.3, 2 * se):
            bad.append(nm)
            print(f"    {nm} {mu:+.2f}{u}  ★偏っている")
        else:
            print(f"    {nm} {mu:+.2f}{u}  偏りなし（ばらつきのみ）")
    if bad:
        print(f"\n  ★ {' と '.join(bad)} に系統的な偏りがある。")
        print("    本番は検証したのと別のルールで動く。select_rule.py の")
        print("    WAVE_MAX / WIND_MAX を、直前情報の目盛りに合わせて取り直すこと。")
    else:
        print("\n  → 偏りが無いので、判定の入れ替わりは『薄まり』にしかならない。")
        print("    実測では 96.1% → 95.3%（−0.8pt）で、買う本数もほぼ減らない（メモ §13-2）。")
        print("    ★閾値はこのまま使う。締めると回収率が上がって見えるが、")
        print("      それは §3 の『閾値の探索はノイズを掴む』そのもの（メモ §13-3）。")


if __name__ == "__main__":
    main()
