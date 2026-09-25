# -*- coding: utf-8 -*-
"""beforeinfo.py -- 公式の直前情報を取る

v22/predict.py の fetch_beforeinfo() をそのまま独立モジュールにしたもの。
当日実行(yosou.py)と日次アーカイブ(collect_before.py)の両方から使う。

取れるもの
  tenji         展示タイム       {艇番: 秒}
  course_in     展示の進入コース  {艇番: コース}   ★本番進入ではない。リークではない
  exhibition_st 展示ST           {艇番: "…"}
  weight        体重             {艇番: kg}
  weather       水面気象          {"風速","気温","水温","波高"}
  wind_w        水面基準の風向     1〜16。17は無風。取れなければ None
  venue_dir     その場の水面の向き  1〜16。取れなければ None

★ 引き継ぎメモ §1 の注意
  raw/ と kfile/ の course は「本番進入」でリーク。
  ここで取れる course_in は「展示進入」で使ってよい。名前が同じなので混同しないこと。
"""
import re
import time
import unicodedata

import requests
from bs4 import BeautifulSoup

BASE = "https://www.boatrace.jp/owpc/pc/race"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "ja"}

_sess = requests.Session()
_sess.headers.update(UA)
_ad = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8)
_sess.mount("https://", _ad)


def _norm(s):
    return unicodedata.normalize("NFKC", s or "").replace(" ", "").replace("　", "")


def _soup(url, timeout=15, min_len=3000, tries=2):
    for i in range(max(1, tries)):
        try:
            r = _sess.get(url, timeout=timeout)
            r.encoding = r.apparent_encoding
            if r.status_code == 200 and len(r.text) >= min_len:
                return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException:
            pass
        if i + 1 < tries:
            time.sleep(0.5 * (i + 1))
    return None


def _closest_class(node, cls):
    p = node
    while p is not None and getattr(p, "get", None) is not None:
        if cls in (p.get("class") or []):
            return p
        p = p.parent
    return None


RE_WIND_CLASS = re.compile(r"weather1_bodyUnitImage\s+is-wind(\d+)")
RE_DIR_CLASS = re.compile(r"weather1_bodyUnitImage\s+is-direction(\d+)")


def _start_timing(row):
    if row is None:
        return None
    txt = None
    for el in row.find_all(True):
        if any("Time" in c for c in (el.get("class") or [])):
            t = _norm(el.get_text())
            if t:
                txt = t
                break
    if not txt:
        txt = _norm(row.get_text())
    m = re.search(r"([FL])?\.(\d{2})", txt)
    if m:
        return f"{m.group(1) or ''}.{m.group(2)}"
    return "F" if "F" in txt else ("L" if "L" in txt else None)


def fetch(date, jcd, rno, tries=2):
    """直前情報。取れなかった項目は空のまま返す。"""
    url = f"{BASE}/beforeinfo?rno={rno}&jcd={jcd:02d}&hd={date}"
    best = {"tenji": {}, "course_in": {}, "exhibition_st": {},
            "weight": {}, "weather": {}, "wind_w": None, "venue_dir": None}
    for attempt in range(max(1, tries)):
        soup = _soup(url)
        if soup is None:
            continue
        out = {"tenji": {}, "course_in": {}, "exhibition_st": {},
               "weight": {}, "weather": {}, "wind_w": None, "venue_dir": None}
        card = soup.find("table", class_=lambda c: c and "is-w748" in c)
        for tb in (card.find_all("tbody") if card else []):
            tr = tb.find("tr")
            if not tr:
                continue
            tds = tr.find_all("td", recursive=False)
            if not tds:
                continue
            lane = None
            for c in tds[0].get("class", []):
                m = re.match(r"is-boatColor(\d)", c)
                if m:
                    lane = int(m.group(1))
                    break
            if lane is None:
                t0 = tds[0].get_text(strip=True)
                lane = int(t0) if t0.isdigit() else None
            if lane is None or not (1 <= lane <= 6):
                continue
            for td in tds:
                t = _norm(td.get_text())
                if lane not in out["tenji"] and re.fullmatch(r"[4-9]\.\d{2}", t):
                    out["tenji"][lane] = float(t)
                mw = re.fullmatch(r"(\d{2}\.\d)kg", t)
                if mw and lane not in out["weight"]:
                    out["weight"][lane] = float(mw.group(1))
        for course, sp in enumerate(
                soup.select(".table1_boatImage1 .table1_boatImage1Number")[:6], start=1):
            t = sp.get_text(strip=True)
            if not (t.isdigit() and 1 <= int(t) <= 6):
                continue
            boat = int(t)
            out["course_in"][boat] = course
            st = _start_timing(_closest_class(sp, "table1_boatImage1"))
            if st:
                out["exhibition_st"][boat] = st
        wbox = soup.find("div", class_="weather1_body") or soup
        for title in ("風速", "気温", "水温", "波高"):
            for unit in wbox.find_all("div", class_="weather1_bodyUnitLabel"):
                tt = unit.find("span", class_="weather1_bodyUnitLabelTitle")
                dd = unit.find("span", class_="weather1_bodyUnitLabelData")
                if tt and dd and title in _norm(tt.get_text()):
                    m = re.search(r"([\d.]+)", dd.get_text(strip=True))
                    if m:
                        out["weather"][title] = float(m.group(1))
                    break
        # ★風向。矢印とコンパスは文字ではなく class に入っている
        #   （band_howto.md §17-1 / §18-1 で確認）。
        #     weather1_bodyUnitImage is-wind<N>        水面の図の上での風の向き
        #     weather1_bodyUnitImage is-direction<N>   その場の水面の向き
        #   w=5 が追い風、w=13 が向かい風、w=9 が左から、w=1 が右から。
        #   w=17 は無風。スマホ版は JavaScript で描いていて取れないので、
        #   ここで見ているPC版だけが頼り。
        html = str(wbox)
        mw = RE_WIND_CLASS.search(html)
        md = RE_DIR_CLASS.search(html)
        out["wind_w"] = int(mw.group(1)) if mw else None
        out["venue_dir"] = int(md.group(1)) if md else None

        # ★気象も点数に入れる。入れないと、展示の数が同じで気象だけ空の
        #   取得結果が前の良い結果を上書きし、波・風が取れず見送りになる。
        #   同点では上書きしない（先に取れたほうを残す）。
        def score(o):
            w = o.get("weather") or {}
            return (len(o["tenji"]) + len(o["course_in"])
                    + 3 * sum(1 for k in ("波高", "風速") if w.get(k) is not None))
        if score(out) > score(best):
            best = out
        if len(out["tenji"]) >= 6 and out["weather"].get("波高") is not None:
            return out
        if attempt + 1 < tries:
            time.sleep(0.6)
    return best


def wind_w(info):
    """features に渡す水面基準の風向 w(1〜16)。無風(17)・不明は None。

    ★17（無風）も None にして返す。features.build_race は
      「向きが無い＝押す力ゼロ」として同じに扱うので、区別する意味がない。
    """
    w = (info or {}).get("wind_w")
    return w if isinstance(w, int) and 1 <= w <= 16 else None


def wave_wind(info):
    """select_rule に渡す (波高cm, 風速m)。取れなければ (None, None)"""
    w = (info or {}).get("weather") or {}
    return w.get("波高"), w.get("風速")
