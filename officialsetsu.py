#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""officialsetsu.py -- uchisankaku が空のとき、公式(boatrace.jp)の出走表から今節成績を作る

★2026-11-19 から uchisankaku が更新されていない（トップページも全場「-R/--:--」、
  その日のページは選手名も無いひな形だけ）。v24 は今節成績と登録番号をそこから取っていたので、
  11/19 は全レース「今節成績が取れません」で見送りになった。

公式の出走表（1レース1ページ）には、各艇の今節成績（その節で走ったレースの R・進入・ST・着順。
1日2枠）と、節の日程（「11月17日 初日 … 最終日」）とレース名がある。そこから uchisankaku の
ページと同じ形（tokuten.parse_page の戻り値）を作る。

  n_runs   … その日より前の走数（uchisankaku は6走まで表示なので上限6）   ← 一致を確かめた
  st_setsu … その日より前の全走の ST の平均（小数2桁）                    ← 一致を確かめた
  tokuten  … 着順点（1着10・2着8・3着6・4着4・5着2・6着1。F・欠などは0）の平均。
             ★ドリーム戦・特選などは uchisankaku が別の点数表を使うので、そこだけずれる（近似）
  rank / genten … 公式からは作れない。rank は None、genten は 0.0
  c_win / c_ren3 / c_st … 公式の出走表に無い（モデルの重要度はほぼ0）。None

  python officialsetsu.py --date 20261120 4 1     # 解析結果を見る
"""
import argparse
import re
import sys
import unicodedata

from bs4 import BeautifulSoup

import officialcard as OC
import tokuten as TK

PTS = {1: 10, 2: 8, 3: 6, 4: 4, 5: 2, 6: 1}
MAX_RUNS = 6                      # uchisankaku の「N走」は6走まで


def _nz(s):
    return unicodedata.normalize("NFKC", s or "").strip()


def _cells(tr):
    return [_nz(td.get_text(" ", strip=True)) for td in tr.find_all("td", recursive=False)]


def _st(s):
    """'.14' → 0.14。F・L・空は None"""
    m = re.fullmatch(r"0?\.(\d{2})", s or "")
    return int(m.group(1)) / 100.0 if m else None


def race_name(soup):
    """「予選 1800m」などの見出しからレース名"""
    for h in soup.find_all(["h3", "h2", "span", "div"]):
        t = _nz(h.get_text(" ", strip=True))
        m = re.fullmatch(r"(\S.{0,18}?)\s*\d{3,4}m", t)
        if m:
            return m.group(1)
    return ""


def parse(html, date):
    """公式の出走表1ページ → {"sched","day_no","n_days","race":{"rno","name","lanes":[...]}}。
    形が違えば None。lanes は tokuten.parse_page の lanes と同じ項目名"""
    soup = BeautifulSoup(html, "html.parser")
    sched, day_no, n_days = TK.parse_tabs(soup, date)
    tbs = OC._rows(soup)
    if len(tbs) != 6:
        return None
    card = OC.parse(html) or []
    lanes = []
    for lane, tb in enumerate(tbs, start=1):
        rows = tb.find_all("tr", recursive=False)
        if len(rows) < 4:
            return None
        c0 = _cells(rows[0])
        i = next((k for k, c in enumerate(c0) if re.match(r"F\s*\d+\s+L\s*\d+", c)), None)
        if i is None:
            return None
        # 今節成績: モーター・ボートの右に1日2枠ずつ。2〜4行目が 進入・ST・着順
        s0 = i + 6
        R, C, ST, CH = c0[s0:s0 + 14], _cells(rows[1]), _cells(rows[2]), _cells(rows[3])
        runs = []
        for k in range(min(14, len(R))):
            if not R[k]:
                continue
            day = k // 2 + 1
            if day_no is not None and day >= day_no:
                continue                      # その日より前の走だけ（uchisankaku と同じ）
            fin = CH[k] if k < len(CH) else ""
            runs.append({"day": day, "r": R[k], "course": C[k] if k < len(C) else "",
                         "st": _st(ST[k] if k < len(ST) else ""),
                         "fin": int(fin) if fin.isdigit() else fin})
        sts = [x["st"] for x in runs if x["st"] is not None]
        pts = [PTS.get(x["fin"], 0) if isinstance(x["fin"], int) else 0 for x in runs]
        cd = card[lane - 1] if len(card) == 6 else {}
        m = re.search(r"(\d{4})\s*/\s*(A1|A2|B1|B2)\s*(.*?)\s+\S+/\S+\s+\d", c0[2] if len(c0) > 2 else "")
        lanes.append({
            "lane": lane, "toban": cd.get("toban"), "cls": m.group(2) if m else None,
            "name": re.sub(r"\s+", " ", m.group(3)).strip() if m else "",
            "n_runs": min(len(runs), MAX_RUNS),
            "st_setsu": round(sum(sts) / len(sts), 2) if sts else None,
            "tokuten": round(sum(pts) / len(pts), 2) if pts else None,
            "rank": None, "genten": 0.0,
            "c_win": None, "c_ren3": None, "c_st": None,
            "src": "official", "runs": runs})
    return {"sched": sched, "day_no": day_no, "n_days": n_days,
            "race": {"rno": None, "name": race_name(soup), "lanes": lanes}}


def fetch_page(date, jcd, rno):
    """1レースぶんを uchisankaku のページと同じ形で返す（races はそのレースだけ）。取れなければ None"""
    html = OC.fetch(date, jcd, rno)
    if not html:
        return None
    p = parse(html, date)
    if not p or p["day_no"] is None:
        return None
    p["race"]["rno"] = rno
    return {"date": date, "jcd": jcd, "sched": p["sched"], "day_no": p["day_no"],
            "n_days": p["n_days"], "races": [p["race"]], "src": "official"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jcd", type=int)
    ap.add_argument("rno", type=int)
    ap.add_argument("--date", required=True)
    a = ap.parse_args()
    pg = fetch_page(a.date, a.jcd, a.rno)
    if not pg:
        sys.exit("取れないか、形が違います")
    print(f"{pg['day_no']}日目/{pg['n_days']}日  {pg['races'][0]['name']}")
    for x in pg["races"][0]["lanes"]:
        print(f"  {x['lane']} {x['toban']} {x['cls']} {x['name']}  走{x['n_runs']} "
              f"ST {x['st_setsu']} 得点率(近似) {x['tokuten']}")


if __name__ == "__main__":
    main()
