#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""windcheck.py -- 直前情報の「水面気象情報」に風向（方角）が入っているか調べる

★何のための確認か
  Kファイルには風向（北・南西…）が入っているが、本番で使っている
  beforeinfo.py は風速・気温・水温・波高しか取っていない。
  スマホ版の画面にはコンパス（その場の水面がどちらを向いているか）と
  風の矢印（水面基準の風向）が出ているので、それが HTML から取れるなら
  「スタート位置から見て 追い風／向かい風／右／左」が本番でも分かる。

  取れるかどうかを確かめるだけのスクリプト。何も変更しない。

  python windcheck.py                  # 既定の3場を見る
  python windcheck.py --jcd 2 4 24     # 場を指定
  python windcheck.py --date 20260922 --rno 1
  python windcheck.py --save out.txt   # 貼り付け用に書き出す

★ページが JavaScript で組み立てられている場合は、ここでは取れない。
  そのときは「風向らしきものが見つからない」と出る。
"""
import argparse
import io
import re
import sys

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"}
PAGES = {
    "pc": "https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd={d}&jcd={j:02d}&rno={r}",
    "sp": "https://www.boatrace.jp/owsp/sp/race/beforeinfo?hd={d}&jcd={j:02d}&rno={r}",
}
# 風向・方角が入っていそうなものを広めに拾う。当たりが分からないので絞らない
HINT = re.compile(r"(wind|Wind|WIND|kaze|風向|方位|compass|Compass|direction|Direction"
                  r"|arrow|Arrow|weather)", re.I)
MARK = "水面気象"


def anchor(html):
    """「水面気象情報」の前後だけを切り出す。無ければ全体"""
    i = html.find(MARK)
    if i < 0:
        return html, False
    return html[max(0, i - 4000): i + 8000], True


def look(html, out):
    part, found = anchor(html)
    out(f"  「{MARK}」の見出し: {'見つかった' if found else '★見つからない'}")
    cls = sorted({c for c in re.findall(r'class="([^"]+)"', part) if HINT.search(c)})
    out(f"  風向らしい class: {len(cls)}種")
    for c in cls[:40]:
        out(f"    {c}")
    srcs = sorted({s for s in re.findall(r'(?:src|href)="([^"]+)"', part)
                   if HINT.search(s)})
    out(f"  風向らしい画像・リンク: {len(srcs)}種")
    for s in srcs[:20]:
        out(f"    {s}")
    # 数字そのものが本文に出ているか。出ていなければ JavaScript で組み立てている
    ms = len(re.findall(r"[0-9]+(?:\.[0-9]+)?m", part))
    out(f"  本文に「風速」: {'ある' if '風速' in part else '★ない'} / 「m」の数値: {ms}個")
    svg = part.count("<svg")
    out(f"  <svg>: {svg}個 / <canvas>: {part.count('<canvas')}個")
    return cls, srcs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="20260922")
    ap.add_argument("--rno", type=int, default=1)
    ap.add_argument("--jcd", type=int, nargs="+", default=[2, 4, 24])
    ap.add_argument("--save", default="")
    ap.add_argument("--html", default="",
                    help="保存済みの HTML を見る（ネットに出ずに調べる）")
    args = ap.parse_args()

    buf = io.StringIO()

    def out(s=""):
        print(s)
        buf.write(s + "\n")

    if args.html:
        out(f"===== 保存済み {args.html}")
        with open(args.html, encoding="utf-8", errors="replace") as f:
            html = f.read()
        out(f"  {len(html):,}バイト")
        look(html, out)
        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                f.write(buf.getvalue())
            print(f"\n書き出しました: {args.save}")
        return 0

    per = {}
    for j in args.jcd:
        for kind, tmpl in PAGES.items():
            url = tmpl.format(d=args.date, j=j, r=args.rno)
            out(f"\n===== 場{j:02d} {kind} {url}")
            try:
                html = requests.get(url, headers=UA, timeout=25).text
            except requests.RequestException as e:
                out(f"  ★取れません: {type(e).__name__} {e}")
                continue
            out(f"  {len(html):,}バイト")
            cls, _ = look(html, out)
            per[(j, kind)] = set(cls)

    # ★場ごとに class が違えば、その中に「その場の向き」が入っている
    for kind in PAGES:
        got = [(j, per[(j, kind)]) for j in args.jcd if (j, kind) in per]
        if len(got) < 2:
            continue
        same = set.intersection(*[c for _, c in got])
        out(f"\n----- {kind}: 場によって違う class")
        any_diff = False
        for j, c in got:
            d = sorted(c - same)
            if d:
                any_diff = True
                out(f"  場{j:02d} だけ: {d}")
        if not any_diff:
            out("  ★全場で同じ。場ごとの向きは class に入っていない")

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
        print(f"\n書き出しました: {args.save}")


if __name__ == "__main__":
    sys.exit(main())
