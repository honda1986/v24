# -*- coding: utf-8 -*-
"""official.py -- 公式サイトから締切予定時刻と3連単オッズを取る

v23/yosou.py の parse_schedule / fetch_official / parse_odds3t / fetch_odds3t を
そのまま持ってきたもの。動いている実績があるので中身は変えていない。
"""
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from features import COMBOS, CIX

BASE = "https://www.boatrace.jp/owpc/pc/race"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "ja"}
JST = timezone(timedelta(hours=9))
NET_LEAD = 3          # ネット投票は本場締切より3分早い

_sess = requests.Session()
_sess.headers.update(UA)
_ad = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8)
_sess.mount("https://", _ad)


def parse_schedule(html):
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.find_all("tr"):
        if "締切予定時刻" not in tr.get_text():
            continue
        t = re.findall(r"\b(\d{1,2}:\d{2})\b", tr.get_text(" "))
        if len(t) >= 12:
            return t[:12]
    return None


def fetch_close(date, jcd):
    """締切予定時刻12個。

    戻り値は (時刻12個 or None, 確定したか)。
    ★通信失敗と「開催なし」を区別する。区別しないと、一度の通信失敗が
      その日の「この場は開催なし」として cache に焼き付き、
      一日中その場を見なくなる（しかもログには何も出ない）。
    """
    try:
        r = _sess.get(f"{BASE}/racelist",
                      params={"rno": 1, "jcd": f"{jcd:02d}", "hd": date}, timeout=20)
        r.raise_for_status()
        r.encoding = "utf-8"
    except requests.RequestException:
        return None, False          # 通信失敗。次の回に取り直す
    return parse_schedule(r.text), True


# ★公式の3連単オッズの書き方（実測 2026-08-22）
#     999.9 以下 … "10.6" "890.6" のように小数第1位まで
#     1000 以上 … "1059" "1373" のように★小数点なしの整数
#   小数点を必須にすると1000倍以上が全部落ちる。穴を含む行が消えるので、
#   「6個そろった行が17行しかない」という形で失敗する。
RE_LOOSE = re.compile(r"\d[\d,]*(?:\.\d+)?")     # 整数も通す（クラスで拾えた場合）
RE_STRICT = re.compile(r"\d[\d,]*\.\d+")         # 小数必須（艇番を拾わないため）


def _num(s, loose=False):
    s = (s or "").strip().replace(" ", "").replace("　", "")
    if not (RE_LOOSE if loose else RE_STRICT).fullmatch(s):
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _by_class(soup):
    """オッズのセルはクラスで拾うのが確実（数字の見た目に依存しない）。

    公式の odds3t は各オッズを <td class="oddsPoint"> で出している。
    行の中の他の数字（艇番など）を拾わずに済む。
    """
    tds = [td for td in soup.find_all("td")
           if any("oddsPoint" in c for c in (td.get("class") or []))]
    if len(tds) != 120:
        return None, len(tds)
    # クラスで場所が確定しているので、整数表記も通す（loose）
    v = [_num(td.get_text(), loose=True) for td in tds]
    # ★3連単のオッズは最低でも1.0。0 は「発売前」「欠場」の印であって値ではない。
    #   ここを通すと 1/0 になり、下流でとんでもない確率になる（実測で踏んだ）。
    if any(x is None or x < 1.0 for x in v):
        return None, len(tds)
    return v, 120


def _place(flat):
    """行優先の120個を組番に割り当てる（20行×6ブロック）"""
    out = [None] * 120
    for r in range(20):
        for g in range(6):
            first = g + 1
            others = [b for b in range(1, 7) if b != first]
            second = others[r // 4]
            third = [b for b in others if b != second][r % 4]
            out[CIX[f"{first}-{second}-{third}"]] = flat[r * 6 + g]
    return None if any(x is None for x in out) else out


def parse_odds3t(html, verbose=False):
    """3連単120点。まずクラスで拾い、駄目なら数字の並びから拾う。"""
    soup = BeautifulSoup(html, "html.parser")

    flat, n = _by_class(soup)
    if flat:
        return _place(flat)
    if n == 120 and verbose:
        print("    [オッズ] oddsPoint は120個あるが、値にならないものがある"
              "（0＝発売前/欠場、または表記が想定外）")

    # --- 予備の経路: 数字の見た目から拾う ---
    best, tb = 0, None
    for t in soup.find_all("table"):
        k = len(re.findall(r">\s*\d[\d,]*\.\d\s*<", str(t)))
        if k > best:
            best, tb = k, t
    if tb is None:
        if verbose:
            print(f"    [オッズ] 表が見つからない（oddsPoint は {n}個）")
        return None
    rows, widths, odd = [], [], []
    for tr in tb.find_all("tr"):
        v, bad = [], []
        for td in tr.find_all("td"):
            x = _num(td.get_text())
            (v if x is not None else bad).append(x if x is not None
                                                else td.get_text(strip=True))
        if v:
            widths.append(len(v))
            if len(v) != 6:
                odd.extend(t for t in bad if t)
        if len(v) == 6:
            rows.append(v)
    if len(rows) != 20:
        if verbose:
            seen = sorted({t[:12] for t in odd})[:8]
            print(f"    [オッズ] oddsPoint {n}個 / 6個そろった行 {len(rows)}行"
                  f"（各行の個数 {sorted(set(widths))}）")
            print(f"    [オッズ] 数字と見なされなかったセル: {seen}")
        return None
    flat = [x for row in rows for x in row]
    if any(x < 1.0 for x in flat):
        if verbose:
            k = sum(1 for x in flat if x < 1.0)
            print(f"    [オッズ] 1.0未満の値が{k}個ある（発売前か欠場艇）")
        return None
    return _place(flat)


def fetch_odds(date, jcd, rno, tries=2, verbose=True):
    """3連単オッズ120点。取れなければ理由を出す"""
    why = ""
    for i in range(max(1, tries)):
        try:
            r = _sess.get(f"{BASE}/odds3t",
                          params={"rno": rno, "jcd": f"{jcd:02d}", "hd": date},
                          timeout=20)
            r.raise_for_status()
            r.encoding = "utf-8"
            o = parse_odds3t(r.text, verbose=(verbose and i + 1 == tries))
            if o:
                return o
            why = f"解析できない（本文{len(r.text):,}文字）"
        except requests.RequestException as e:
            why = type(e).__name__
        if i + 1 < tries:
            time.sleep(1.0)
    if verbose:
        print(f"    [オッズが取れない理由] {why}")
    return None


def net_close(hhmm):
    """本場締切 → ネット締切(3分前)"""
    hh, mm = (int(x) for x in hhmm.split(":"))
    t = datetime(2000, 1, 1, hh, mm) - timedelta(minutes=NET_LEAD)
    return t.strftime("%H:%M")


def mins_left(hhmm, now):
    """締切まであと何分か"""
    if not hhmm:
        return None
    try:
        hh, mm = (int(z) for z in hhmm.split(":"))
    except ValueError:
        return None
    return (hh * 60 + mm) - (now.hour * 60 + now.minute)
