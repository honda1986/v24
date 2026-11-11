#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""oddsx.py -- 3連単以外の賭式のオッズ（公式 boatrace.jp）

★band_howto.md §30。判定時のオッズは最終の売上の1〜2割しか入っていない段階のもので、
  3連単だけを見ていても締切直前のお金が運ぶ情報は取れない（Fable の調査、2026-11-11）。
  単勝・複勝は控除率が低くプールも薄いので、3連単より歪みが残っている可能性がある。
  判定時の値は後から取り直せないので、まず貯める。判定には使っていない。

  ページ             中身                              並び
  oddstf   単勝 6 / 複勝 6（"1.0-1.5" の幅）            艇番 1〜6
  odds2tf  2連単 30 / 2連複 15                          PAIRS / PAIRS2
  odds3f   3連複 20                                     TRIOS
  oddsk    拡連複 15（幅）                               PAIRS2

  表は「1着（小さいほう）の艇ごとの列」に「相手の艇番, オッズ」が並ぶ。
  3連複は2着の艇番が rowspan で縦にまたがるので、表を格子に広げてから読む。

  python oddsx.py 24 12 --date 20261110
"""
import argparse
import re
import time

import requests
from bs4 import BeautifulSoup

from official import BASE, JST, _sess

PAIRS = [(a, b) for a in range(1, 7) for b in range(1, 7) if b != a]            # 2連単 30
PAIRS2 = [(a, b) for a in range(1, 7) for b in range(a + 1, 7)]                 # 2連複・拡連複 15
TRIOS = [(a, b, c) for a in range(1, 7) for b in range(a + 1, 7) for c in range(b + 1, 7)]  # 3連複 20
PAGES = ("oddstf", "odds2tf", "odds3f", "oddsk")


def _num(t):
    t = t.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        return float(t)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", t)
    if m:
        return [float(m.group(1)), float(m.group(2))]
    return None                         # 欠場・未発売など


def _boat(td):
    for c in td.get("class", []):
        m = re.match(r"is-boatColor(\d)$", c)
        if m:
            t = td.get_text(strip=True)
            return int(t) if t.isdigit() else None
    return None


def _is_point(td):
    return any("oddsPoint" in c for c in td.get("class", []))


def _tables(soup):
    return [t for t in soup.find_all("table") if t.find("td", class_=lambda c: c and "oddsPoint" in c)]


def _grid(table):
    """rowspan を広げた格子（行ごとの td の並び）。見出しの行は除く"""
    rows, carry = [], {}
    for tr in table.find_all("tr"):
        tds = tr.find_all(["td", "th"], recursive=False)
        if tds and all(t.name == "th" for t in tds):
            continue
        row, i = [], 0
        it = iter(tds)
        while True:
            if i in carry and carry[i][1] > 0:
                row.append(carry[i][0])
                carry[i] = (carry[i][0], carry[i][1] - 1)
                i += 1
                continue
            td = next(it, None)
            if td is None:
                break
            rs = int(td.get("rowspan") or 1)
            if rs > 1:
                carry[i] = (td, rs - 1)
            row.append(td)
            i += 1
        rows.append(row)
    return rows


def _pairs_by_column(table, width):
    """列ごとに (相手の艇番…, オッズ) を読む。width は1列ぶんの td の数"""
    out = []
    for row in _grid(table):
        if row and _boat(row[0]) is not None and len(row) == 12 and not any(_is_point(t) for t in row):
            continue                    # 列見出し（艇番と名前）の行
        for k in range(len(row) // width):
            cell = row[k * width:(k + 1) * width]
            if not _is_point(cell[-1]):
                continue
            boats = [_boat(t) for t in cell[:-1]]
            v = _num(cell[-1].get_text())
            if all(b is not None for b in boats):
                out.append(((k + 1, *boats), v))
    return out


def parse_tf(html):
    """{"win": [6], "place": [[下限, 上限] x6]}。艇番の順"""
    soup = BeautifulSoup(html, "html.parser")
    win, place = [None] * 6, [None] * 6
    for t in _tables(soup):
        title = t.get_text()
        for tr in t.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            pt = [td for td in tds if _is_point(td)]
            b = _boat(tds[0]) if tds else None
            if not pt or b is None:
                continue
            v = _num(pt[0].get_text())
            if "複勝" in title:
                place[b - 1] = v
            else:
                win[b - 1] = v
    return {"win": win, "place": place} if any(win) else None


def parse_2tf(html):
    """{"2t": [30, PAIRS の並び], "2f": [15, PAIRS2 の並び]}"""
    soup = BeautifulSoup(html, "html.parser")
    ts = _tables(soup)
    if len(ts) < 2:
        return None
    d2t = dict(_pairs_by_column(ts[0], 2))
    d2f = {tuple(sorted(k)): v for k, v in _pairs_by_column(ts[1], 2)}
    return {"2t": [d2t.get(p) for p in PAIRS], "2f": [d2f.get(p) for p in PAIRS2]}


def parse_3f(html):
    """{"3f": [20, TRIOS の並び]}"""
    soup = BeautifulSoup(html, "html.parser")
    ts = _tables(soup)
    if not ts:
        return None
    d = {tuple(sorted(k)): v for k, v in _pairs_by_column(ts[0], 3)}
    return {"3f": [d.get(t) for t in TRIOS]}


def parse_k(html):
    """{"k": [[下限, 上限] x15, PAIRS2 の並び]}"""
    soup = BeautifulSoup(html, "html.parser")
    ts = _tables(soup)
    if not ts:
        return None
    d = {tuple(sorted(k)): v for k, v in _pairs_by_column(ts[0], 2)}
    return {"k": [d.get(p) for p in PAIRS2]}


PARSE = {"oddstf": parse_tf, "odds2tf": parse_2tf, "odds3f": parse_3f, "oddsk": parse_k}


def fetch(date, jcd, rno, pages=PAGES, gap=0.3, timeout=15):
    """指定のページを取って1つの dict にまとめる。取れなかったページは入らない"""
    out = {}
    for i, page in enumerate(pages):
        if i:
            time.sleep(gap)
        try:
            r = _sess.get(f"{BASE}/{page}", params={"rno": rno, "jcd": f"{jcd:02d}", "hd": date},
                          timeout=timeout)
            r.encoding = "utf-8"
            if r.status_code != 200 or len(r.text) < 20000:
                continue
            got = PARSE[page](r.text)
        except (requests.RequestException, ValueError, AttributeError, IndexError):
            continue
        if got:
            out.update(got)
    return out


def main():
    from datetime import datetime
    ap = argparse.ArgumentParser()
    ap.add_argument("jcd", type=int)
    ap.add_argument("rno", type=int)
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or datetime.now(JST).strftime("%Y%m%d")
    x = fetch(date, args.jcd, args.rno)
    for k, v in x.items():
        print(k, v)


if __name__ == "__main__":
    main()
