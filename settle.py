#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""settle.py -- 買った記録に結果を入れる（予想サイト用）

history.json の picks は、通知した時点では結果が空。翌日 Kファイルが出たら
的中したか・払戻がいくらかを入れる。motor.yml が毎朝 v22 の kfile を
持ってくるので、そのついでに走らせる。

  python settle.py --kfile /tmp/v22/kfile

★紙で回している間の唯一の答え合わせなので、ここが狂うと何も分からなくなる。
  だから「Kファイルにそのレースが無い」場合は空のままにして、
  勝手に不的中扱いにはしない。
"""
import argparse
import glob
import gzip
import json
import os

SITE = "history.json"
BET_YEN = 100


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kfile", default="../v22/kfile")
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

    if filled:
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


if __name__ == "__main__":
    main()
