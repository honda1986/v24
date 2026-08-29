#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""officialcard.py -- 公式(boatrace.jp)の出走表から CARD 項目を取る

★なぜ要るのか
  info.kyotei.fun は GitHub Actions から時々まったく届かない（実測）。
  uchisankaku は確実に届くが、**平均ST と ボート2連率 を持っていない**。
  この2つを別のもので埋めたのが v23 の不具合。公式は両方持っている。

★ただし、これを本番に入れる前に cardcheck.py で
  info.kyotei.fun と数値が一致することを必ず確かめること。
  桁（34.5 か 0.345 か）がずれていても、モデルは黙って動く。

  python officialcard.py --dump 24 1     # ページの構造を見る
  python officialcard.py 24 1            # 解析結果を見る
"""
import argparse
import re
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from official import BASE, JST, UA, _sess

CLS_MAP = {"A1": 4, "A2": 3, "B1": 2, "B2": 1}
NUM = r"-?\d+(?:\.\d+)?"


def fetch(date, jcd, rno, tries=3):
    url = f"{BASE}/racelist"
    why = ""
    for i in range(max(1, tries)):
        try:
            r = _sess.get(url, params={"rno": rno, "jcd": f"{jcd:02d}", "hd": date},
                          timeout=30)
            r.encoding = "utf-8"
            if r.status_code == 200 and len(r.text) > 20000:
                return r.text
            why = f"HTTP {r.status_code} / {len(r.text)}文字"
        except requests.RequestException as e:
            why = type(e).__name__
        if i + 1 < tries:
            time.sleep(1.5 * (i + 1))
    print(f"    [公式出走表が取れない理由] {why}")
    return None


def _rows(soup):
    """6艇ぶんの行を、登録番号(4桁)を手がかりに拾う"""
    out = []
    for tb in soup.find_all("tbody"):
        t = tb.get_text(" ", strip=True)
        if re.search(r"\b\d{4}\s*/\s*(A1|A2|B1|B2)\b", t):
            out.append(tb)
    return out


def parse(html):
    """枠番順6要素。取れなかった項目は None（既定値で埋めない）"""
    soup = BeautifulSoup(html, "html.parser")
    tbs = _rows(soup)
    if len(tbs) != 6:
        return None
    out = []
    for lane, tb in enumerate(tbs, start=1):
        t = re.sub(r"\s+", " ", tb.get_text(" ", strip=True))
        d = {"lane": lane, "toban": None, "cls_val": None, "age": None,
             "weight": None, "f_count": None, "l_count": None, "avg_st": None,
             "n_win": None, "n_2ren": None, "l_win": None, "l_2ren": None,
             "m_2ren": None, "b_2ren": None, "name": ""}

        m = re.search(r"(\d{4})\s*/\s*(A1|A2|B1|B2)", t)
        if m:
            d["toban"] = int(m.group(1))
            d["cls_val"] = CLS_MAP[m.group(2)]
        m = re.search(r"(\d{1,2})\s*歳", t)
        if m:
            d["age"] = int(m.group(1))
        m = re.search(r"(\d{2}(?:\.\d)?)\s*kg", t)
        if m:
            d["weight"] = float(m.group(1))
        m = re.search(r"F\s*(\d+)", t)
        if m:
            d["f_count"] = int(m.group(1))
        m = re.search(r"L\s*(\d+)", t)
        if m:
            d["l_count"] = int(m.group(1))
        # F/L のあとに来る 0.xx が平均ST
        m = re.search(r"L\s*\d+\s+(0?\.\d{2})", t)
        if m:
            d["avg_st"] = float(m.group(1))

        # 平均STの後ろに 全国3個 → 当地3個 → モーター(番号+2個) → ボート(番号+2個)
        tail = t[m.end():] if m else t
        nums = re.findall(NUM, tail)
        if len(nums) >= 14:
            v = [float(x) for x in nums[:14]]
            d["n_win"], d["n_2ren"] = v[0], v[1] / 100.0
            d["l_win"], d["l_2ren"] = v[3], v[4] / 100.0
            d["m_2ren"] = v[7] / 100.0          # v[6] はモーター番号
            d["b_2ren"] = v[10] / 100.0         # v[9] はボート番号
        out.append(d)
    return out


def fetch_card(date, jcd, rno):
    html = fetch(date, jcd, rno)
    return parse(html) if html else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jcd", type=int)
    ap.add_argument("rno", type=int)
    ap.add_argument("--date", default=None)
    ap.add_argument("--dump", action="store_true",
                    help="解析できないとき、行の中身をそのまま出す")
    args = ap.parse_args()
    date = args.date or datetime.now(JST).strftime("%Y%m%d")

    html = fetch(date, args.jcd, args.rno)
    if not html:
        sys.exit(1)
    if args.dump:
        soup = BeautifulSoup(html, "html.parser")
        tbs = _rows(soup)
        print(f"登録番号らしき行 {len(tbs)}個")
        for i, tb in enumerate(tbs[:6], 1):
            t = re.sub(r"\s+", " ", tb.get_text(" ", strip=True))
            print(f"\n--- {i}枠 ---\n{t[:400]}")
        return
    rc = parse(html)
    if not rc:
        print("★解析できない。--dump で中身を見ること")
        sys.exit(1)
    for x in rc:
        print(f"  {x['lane']}枠 登番{x['toban']} 級{x['cls_val']} "
              f"{x['age']}歳 {x['weight']}kg F{x['f_count']} "
              f"平均ST {x['avg_st']}  全国 {x['n_win']}/{x['n_2ren']}  "
              f"当地 {x['l_win']}/{x['l_2ren']}  "
              f"モ {x['m_2ren']}  ボ {x['b_2ren']}")


if __name__ == "__main__":
    main()
