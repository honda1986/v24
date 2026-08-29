#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cardcheck.py -- 出走表の取得元3つを突き合わせる

学習データ raw/ は info.kyotei.fun 由来。本番で別の取得元を使うなら、
**同じレースで数値が一致すること**を確かめてからでないと v23 と同じ轍を踏む。
桁がずれていても（45.16 か 0.4516 か）モデルは黙って動く。

取得元とコスト
  info.kyotei.fun  1レース1ページ（12倍かかる）。Actions から時々届かない
  公式 boatrace.jp 1レース1ページ。遅い（1件8〜10秒）が確実に届く
  uchisankaku      ★1ページに12レース分。今節成績のために既に取っている
                   ただし 平均ST と ボート2連率 を持っていない

  python cardcheck.py
"""
import argparse
from collections import defaultdict
from datetime import datetime

import officialcard as OC
import racecard as RC
import tokuten as TK
from official import JST

CLS_MAP = {"A1": 4, "A2": 3, "B1": 2, "B2": 1}
FIELDS = ["cls_val", "age", "weight", "f_count", "avg_st",
          "n_win", "n_2ren", "l_win", "l_2ren", "m_2ren", "b_2ren"]


def from_sakura(page, rno):
    """uchisankaku の1レース分を CARD の形に直す。

    ★桁をそろえる。sakura は 2連率を 45.16 のまま持っている。
      学習データ(info.kyotei.fun 由来)は 0.4516。ここを間違えると
      モデルは100倍の値を食うが、エラーは出ない。
    """
    for r in page.get("races") or []:
        if r["rno"] != rno:
            continue
        out = []
        for x in sorted(r["lanes"], key=lambda z: z["lane"]):
            def pct(v):
                return None if v is None else (v / 100.0 if v > 1.0 else v)
            out.append({
                "lane": x["lane"],
                "cls_val": CLS_MAP.get((x.get("cls") or "")[:2]),
                "age": x.get("age"), "weight": x.get("weight"),
                "f_count": x.get("f_count"),
                "avg_st": None,                 # ★持っていない
                "n_win": x.get("n_win"), "n_2ren": pct(x.get("n_2ren")),
                "l_win": x.get("l_win"), "l_2ren": pct(x.get("l_2ren")),
                "m_2ren": pct(x.get("m_2ren")),
                "b_2ren": None,                 # ★持っていない
            })
        return out if len(out) == 6 else None
    return None


def compare(name, ref, other, diff):
    for x, y in zip(ref, other):
        for f in FIELDS:
            u, v = x.get(f), y.get(f)
            diff[(name, f)].append(None if (u is None or v is None)
                                   else abs(float(u) - float(v)))


def report(name, diff):
    print(f"\n=== {name} を info.kyotei.fun と比べる ===")
    print(f"  {'項目':<10}{'一致':>10}{'最大ずれ':>12}  判定")
    bad, none = [], []
    for f in FIELDS:
        v = diff[(name, f)]
        got = [x for x in v if x is not None]
        if not got:
            print(f"  {f:<10}{'—':>10}{'欠測':>12}  この取得元には無い")
            none.append(f)
            continue
        same = sum(1 for x in got if x < 1e-6)
        mx = max(got)
        ok = mx < 0.005 or (f in ("n_win", "l_win") and mx < 0.02)
        print(f"  {f:<10}{same}/{len(got):<8}{mx:>12.4f}  "
              f"{'一致' if ok else '別定義（入れ替え不可）'}")
        if not ok:
            bad.append(f)
    return bad, none


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--races", default="24:10,24:12,7:10,20:10,22:10")
    args = ap.parse_args()
    date = args.date or datetime.now(JST).strftime("%Y%m%d")

    diff = defaultdict(list)
    pages, n = {}, 0
    sess = TK.make_session()
    for spec in args.races.split(","):
        jcd, rno = (int(x) for x in spec.split(":"))
        ref = RC.fetch_racecard(date, jcd, rno, tries=2)
        if not ref:
            print(f"  {jcd:02d}場 {rno}R  info.kyotei.fun が取れず。とばす")
            continue
        if jcd not in pages:
            html = TK.fetch(sess, jcd, date)
            pages[jcd] = TK.parse_page(html, date) if html else None
        sk = from_sakura(pages[jcd], rno) if pages.get(jcd) else None
        of = OC.fetch_card(date, jcd, rno)
        got = []
        if sk:
            compare("uchisankaku", ref, sk, diff)
            got.append("sakura")
        if of:
            compare("公式", ref, of, diff)
            got.append("公式")
        n += 6
        print(f"  {jcd:02d}場 {rno}R  比較できた取得元: {got or 'なし'}")

    if not n:
        raise SystemExit("★ 突き合わせられませんでした")
    print(f"\n突き合わせ {n}艇")

    b1, n1 = report("uchisankaku", diff)
    b2, n2 = report("公式", diff)

    print("\n" + "=" * 56)
    if not b1 and len(n1) == len(FIELDS):
        print("uchisankaku: ★1項目も比べられていない。parse_page が失敗している")
    elif not b1:
        print(f"uchisankaku: 一致。{' '.join(n1)} 以外はここから取ってよい")
        print("  → 1場1リクエストで済むので、これを主にする価値がある")
    else:
        print(f"uchisankaku: {' '.join(b1)} は別定義。学習データと違う値になるので使えない")
    if not b2 and not n2:
        print("公式: 全項目一致。届かないときの代わりに使える")
    elif b2:
        print(f"公式: {' '.join(b2)} は別定義。学習データと違う値になるので使えない")
    else:
        print(f"公式: {' '.join(n2)} が取れていない。parse() を直すこと")


if __name__ == "__main__":
    main()
