#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""windcheck.py -- 直前情報から風向（コンパスと風の矢印）を取り出す

★何のための確認か
  Kファイルには風向が **方位**（北・南西…）で入っているが、それをそのまま
  使うには「その場の水面がどちらを向いているか」を24場ぶん手で書く必要が
  あり、1場間違えただけで追い風と向かい風が入れ替わって静かに壊れる。

  直前情報のPC版には class として2つ入っている（2026-09-23 に確認）。

    weather1_bodyUnitImage is-direction<N>   コンパス（その場の向き）
    weather1_bodyUnitImage is-wind<N>        風の矢印

  知りたいのは **is-wind が方位なのか、水面基準なのか**。
  水面基準なら、場ごとの向きの表を作らずに
  「スタート位置から見て 追い風／向かい風／右／左」が直接読める。

  判別のしかた:
    ・同じ場で風向がいろいろ変わる日を取り、Kファイルの wind_dir と
      is-wind の対応を見る
    ・複数の場で is-direction が違えば、それが場の向き

  python windcheck.py --date 20260921 --jcd 13 --rno 1-12
  python windcheck.py --date 20260921 --jcd 1 5 6 9 10 12 13 15 16 17 18 --rno 1
  python windcheck.py --classes --jcd 2          # class を並べるだけ（調査用）
  ... --save C:\\boat\\wind.txt                   # 貼り付け用に書き出す

★読むだけ。何も変更しない。
"""
import argparse
import io
import re
import sys
import time

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"}
URL = "https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd={d}&jcd={j:02d}&rno={r}"
MARK = "水面気象"
HINT = re.compile(r"(wind|direction|compass|arrow|weather)", re.I)

RE_DIR = re.compile(r"weather1_bodyUnitImage\s+is-direction(\d+)")
RE_WIND = re.compile(r"weather1_bodyUnitImage\s+is-wind(\d+)")


def fetch(date, jcd, rno):
    try:
        return requests.get(URL.format(d=date, j=jcd, r=rno), headers=UA,
                            timeout=25).text
    except requests.RequestException as e:
        return f"★取れません: {type(e).__name__} {e}"


def label(html, title):
    """「風速 2m」のような値を1つ取る。無ければ None"""
    i = html.find(title)
    if i < 0:
        return None
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:m|cm|℃)", html[i:i + 400])
    return m.group(1) if m else None


def rows(date, jcds, rnos, out, wait=0.5):
    out("date\tjcd\trno\tdirection\twind\t風速\t波高")
    n = 0
    for j in jcds:
        for r in rnos:
            html = fetch(date, j, r)
            if html.startswith("★"):
                out(f"{date}\t{j:02d}\t{r}\t{html}")
                continue
            if MARK not in html:
                out(f"{date}\t{j:02d}\t{r}\t-\t-\t-\t-\t（開催なし）")
                continue
            d = RE_DIR.search(html)
            w = RE_WIND.search(html)
            out(f"{date}\t{j:02d}\t{r}\t"
                f"{d.group(1) if d else '?'}\t{w.group(1) if w else '?'}\t"
                f"{label(html, '風速') or '-'}\t{label(html, '波高') or '-'}")
            n += 1
            time.sleep(wait)
    out(f"\n取れたレース {n}件")


def classes(date, jcds, rno, out):
    for j in jcds:
        html = fetch(date, j, rno)
        out(f"\n===== 場{j:02d} {len(html):,}バイト")
        if html.startswith("★"):
            out("  " + html)
            continue
        i = html.find(MARK)
        part = html if i < 0 else html[max(0, i - 4000): i + 8000]
        out(f"  「{MARK}」: {'見つかった' if i >= 0 else '★見つからない（開催なし？）'}")
        for c in sorted({c for c in re.findall(r'class="([^"]+)"', part)
                         if HINT.search(c)}):
            out(f"    {c}")


def expand(vals):
    """1 2 5 や 1-12 を展開する"""
    out = []
    for v in vals:
        if "-" in str(v):
            a, b = str(v).split("-", 1)
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(v))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="20260921")
    ap.add_argument("--jcd", nargs="+", default=["13"])
    ap.add_argument("--rno", nargs="+", default=["1-12"])
    ap.add_argument("--classes", action="store_true", help="class を並べるだけ")
    ap.add_argument("--save", default="")
    args = ap.parse_args()

    buf = io.StringIO()

    def out(s=""):
        print(s)
        buf.write(s + "\n")

    jcds, rnos = expand(args.jcd), expand(args.rno)
    if args.classes:
        classes(args.date, jcds, rnos[0], out)
    else:
        rows(args.date, jcds, rnos, out)

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
        print(f"\n書き出しました: {args.save}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
