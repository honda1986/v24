# -*- coding: utf-8 -*-
"""racecard.py -- 出走表の数値を取る (info.kyotei.fun)

★なぜこの取得元なのか
  学習データ `raw/` は v22/backfill.py が info.kyotei.fun から作っている。
  本番も同じ取得元・同じ解釈でなければ、学習と本番で特徴量の中身が変わる。

  v23 はここを uchisankaku から取っていたため、
    avg_st  … 平均ST のはずが「コース別ST」が入っていた
    b_2ren  … 常に None だった
  という食い違いがあった。v24 はそれを直している。

  v22/predict.py の fetch_racecard() をそのまま移植したもの。中身は変えていない。

■ 取れるもの (枠番順の6要素)
  lane cls_val age weight f_count avg_st n_win n_2ren l_win l_2ren m_2ren b_2ren
  tenji(展示タイム) course_in(★この取得元では本番進入の可能性がある。使わない) name
"""
import re
import time

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
sess = requests.Session()
sess.headers.update(UA)
_ad = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8)
sess.mount("https://", _ad)

RE_AGE = re.compile(r"\((\d{2})\)")
RE_CLS = re.compile(r"([A12B]{2})")
RE_WEIGHT = re.compile(r"(\d+)kg", re.IGNORECASE)
CLS_MAP = {"A1": 4, "A2": 3, "B1": 2, "B2": 1}


def _lane_from_class(td):
    div = td.find("div", class_=lambda c: c and "ng1r" in c)
    if not div:
        return None
    for cls in div.get("class", []):
        m = re.match(r"ng1r(\d)$", cls)
        if m:
            return int(m.group(1))
    return None


def fetch_racecard(date: str, jcd: int, rno: int, tries: int = 2):
    """kyotei.fun の結合ページから選手データを取得。

    取れなかったときは理由を必ず表示する。黙って None を返すと
    「遮断されている」のか「まだ掲載されていない」のか切り分けられない。
    """
    url = f"https://info.kyotei.fun/info-{date}-{jcd:02d}-{rno}.html"
    why, r = "", None
    for i in range(max(1, tries)):
        try:
            r = sess.get(url, timeout=12)
            r.encoding = r.apparent_encoding
            if r.status_code == 200 and len(r.text) >= 5000:
                why = ""
                break
            why = f"HTTP {r.status_code} / 本文{len(r.text)}文字"
            if r.status_code in (403, 429):      # 遮断・制限は待っても同じ
                break
        except requests.RequestException as e:
            why = type(e).__name__
        if i + 1 < tries:
            time.sleep(1.0)
    if why:
        print(f"    [出走表が取れない理由] {why}  {url}")
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    base = {i + 1: {"lane": i + 1, "age": 30, "cls_val": 1, "weight": 50, "f_count": 0,
                    "avg_st": 0.17, "n_win": 0.0, "n_2ren": 0.0, "l_win": 0.0, "l_2ren": 0.0,
                    "m_2ren": 0.0, "b_2ren": 0.0, "tenji": None, "course_in": i + 1,
                    "name": "", "tenji_st": ""} for i in range(6)}
    label = ""
    for tr in soup.find_all("tr"):
        tds = tr.find_all(["td", "th"])
        if not tds:
            continue
        if len(tds) >= 7:
            label = tds[0].get_text(strip=True).replace("\n", "").replace(" ", "").replace("\u3000", "")
            data = tds[-6:]
        elif len(tds) == 6 and label:
            data = tds
        else:
            label = ""
            continue
        for i in range(6):
            td = data[i]
            txt = td.get_text(" ", strip=True).replace(" ", "").replace("\u3000", "").replace("\n", "")
            lane = i + 1
            if "選手名" in label:
                nm = re.sub(r"\(.*", "", txt).strip()
                if nm:
                    base[lane]["name"] = nm[:8]
                m = RE_AGE.search(txt)
                if m:
                    base[lane]["age"] = int(m.group(1))
            elif "選手情報" in label or "支部" in label:
                mc = RE_CLS.search(txt)
                if mc:
                    base[lane]["cls_val"] = CLS_MAP.get(mc.group(1), 1)
                mw = RE_WEIGHT.search(txt)
                if mw:
                    base[lane]["weight"] = int(mw.group(1))
            elif "級過去2期" in label:
                mc = RE_CLS.search(txt)
                if mc:
                    base[lane]["cls_val"] = CLS_MAP.get(mc.group(1), 1)
            elif "全国" in label and "勝率" in label:
                m2 = re.search(r"^([\d\.]+)", txt)
                mw = re.search(r"\(([\d\.]+)\)", txt)
                if m2:
                    v = float(m2.group(1))
                    base[lane]["n_2ren"] = v / 100.0 if v > 1.0 else v
                if mw:
                    base[lane]["n_win"] = float(mw.group(1))
            elif "当地" in label and "勝率" in label:
                m2 = re.search(r"^([\d\.]+)", txt)
                mw = re.search(r"\(([\d\.]+)\)", txt)
                if m2:
                    v = float(m2.group(1))
                    base[lane]["l_2ren"] = v / 100.0 if v > 1.0 else v
                if mw:
                    base[lane]["l_win"] = float(mw.group(1))
            elif "モータ" in label and "2連率" in label:
                m = re.search(r"^([\d\.]+)", txt)
                if m:
                    v = float(m.group(1))
                    base[lane]["m_2ren"] = v / 100.0 if v > 1.0 else v
            elif "ボート" in label and "2連率" in label:
                m = re.search(r"^([\d\.]+)", txt)
                if m:
                    v = float(m.group(1))
                    base[lane]["b_2ren"] = v / 100.0 if v > 1.0 else v
            elif "平均ST" in label:
                try:
                    base[lane]["avg_st"] = float(txt)
                except ValueError:
                    pass
            elif "フライング" in label:
                try:
                    base[lane]["f_count"] = int(txt)
                except ValueError:
                    pass
            elif label == "展示":
                # ★既定値を入れない。取れなければ None のままにする。
                #   6.80 のような「もっともらしい既定値」を入れると、
                #   展示が出ていないレースを本物と見分けられなくなる。
                try:
                    v = float(txt)
                    if 5.0 < v < 8.5:
                        base[lane]["tenji"] = v
                except ValueError:
                    pass
            elif label == "コースIN":
                c = _lane_from_class(td)
                if c:
                    base[lane]["course_in"] = c
    out = [base[i + 1] for i in range(6)]
    # ★HTTP 200 でも中身が別物（表の作りが変わった／未掲載の枠だけのページ）だと、
    #   既定値のままの6艇が「取れた」ように見えてしまう。それを本番で使うと
    #   でたらめな数字で買い目を作り、しかもエラーが出ない。
    #   全国勝率は必ず正の値なので、これで見分ける。
    named = sum(1 for x in out if x["name"])
    win_ok = sum(1 for x in out if (x["n_win"] or 0) > 0)
    # 新人は全国勝率が本当に 0.00 になり得るので、6艇すべてを要求しない。
    # 選手名か勝率のどちらかが揃っていれば、表を読めたとみなす。
    if named < 6 and win_ok < 5:
        print(f"    [出走表] 選手名{named}/6・全国勝率{win_ok}/6。"
              f"既定値のページとみなす  {url}")
        return None
    return out
