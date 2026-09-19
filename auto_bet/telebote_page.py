#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""telebote_page.py -- テレボート（bu.tbbr.jp）の画面操作だけを閉じ込めたファイル

サイトの作りが変わったとき、直すのがこのファイルだけで済むように、
画面に触るコードはここにしか置きません。

採取していただいた codegen の記録から起こした流れ:

  場を選ぶ → レースを選ぶ → 1着/2着/3着をチェック（#bet1-1 など）
  → 口数を入れる（1口 = 100円）→「ベットリストに追加して投票へ進む」
  →「次へ」→ 確認画面 → 合計金額を入れる →「投票」→ 完了

★ログイン情報はここにも他のどこにも書きません。
  login モードで手でログインし、その Chrome プロファイルを使い回します。

★印の付いたセレクタは、まだ確かめていない推測です。dry モードで確かめてください。
"""
import os
import re
import unicodedata

# --------------------------------------------------------------------------
# 画面の場所。codegen の記録から起こしたもの
# --------------------------------------------------------------------------
SELECTORS = {
    # レースは URL で直接開ける。jyoCode は v24 の jcd と同じ番号
    # ★1桁の場（浜名湖6・蒲郡7・常滑8・津9）で 06 と 6 のどちらかは未確認
    "race_url": "https://bu.tbbr.jp/bet?hatsubaiKbn=0&jyoCode={jcd:02d}&raceNo={rno:02d}",
    "place_link": "text={place}",          # race_url が使えないときの控え
    "race_link": "text={rno}R",            # 同上
    # 勝式を3連単にする。押すところ → 出てくる中から選ぶところ
    "bet_type_open": "role=button[name=\"連単\"]",
    "bet_type_trifecta": "role=radio[name=\"3連単\"]",
    # 着順のチェックボックス。{d} に艇番が入る
    "lane1": "#bet1-{d}",
    "lane2": "#bet2-{d}",
    "lane3": "#bet3-{d}",
    "amount": "role=textbox",              # 口数（1口 = 100円）
    "add_to_slip": "text=ベットリストに追加して投票へ進む",
    "to_confirm": "role=button[name=\"次へ\"]",
    "confirm_mark": "text=投票はまだ完了していません",   # 確認画面に着いた印
    "confirm_area": "table",               # 照合に使う範囲。買い目の表だけを見る
    "confirm_area_fallback": "body",       # 表が取れないときは画面全体で見る
    "total_amount": "role=textbox",        # 確認画面で打ち直す合計金額
    "submit": "role=button[name=\"投票\"]",
    "done_mark": "text=場を変更して投票",   # 投票完了の印
    "logged_in_mark": "text=マイページ",    # ログイン済みのときだけ出るもの
}

# 確認画面の合計欄の書き方。ここが変わったら直す
TOTAL_BETS = "合計ベット数{n}ベット"
TOTAL_YEN = "合計金額{yen}円"
BET_TYPE = "3連単"

# 金額欄が「口数（100円＝1口）」なら True、「円」そのままなら False
AMOUNT_IN_UNITS = True

# 待ち時間は固定秒ではなく、要素が出るのを待つ
TIMEOUT_MS = 20000


class SelectorNotSet(Exception):
    """SELECTORS が埋まっていない"""


class BetAborted(Exception):
    """画面が想定と違う。押していないことは確か。この周は打ち切る"""


class BetUncertain(Exception):
    """★投票を押した後で失敗した。通ったかどうか分からない

    こうなったら、押していないものとして次の周でもう一度買ってはいけない。
    呼び出し側は投票済みとして記録し、動作を止めて人に確認してもらうこと。
    """


# 空だと dry / live が始められないもの。race_url があれば place_link / race_link は要らない
REQUIRED = ("lane1", "lane2", "lane3", "amount", "to_confirm", "confirm_area", "submit")


def missing_selectors():
    """埋まっていない SELECTORS を並べる（起動時に見て、動く前に止めるため）"""
    miss = [k for k in REQUIRED if not (SELECTORS.get(k) or "").strip()]
    if not (SELECTORS.get("race_url") or "").strip():
        miss += [k for k in ("place_link", "race_link")
                 if not (SELECTORS.get(k) or "").strip()]
    return miss


def _sel(name, **fmt):
    v = (SELECTORS.get(name) or "").strip()
    if not v:
        raise SelectorNotSet(
            f"telebote_page.py の SELECTORS['{name}'] が空です。\n"
            "  playwright codegen --channel=chrome https://bu.tbbr.jp/\n"
            "で実際に1点買ってみて、出てきたコードから写してください。"
        )
    return v.format(**fmt) if fmt else v


def norm(text):
    """比較のために表記を揃える（全角→半角、区切りを - に、桁区切りのカンマを落とす）"""
    t = unicodedata.normalize("NFKC", text or "")
    for ch in "＝=−–—ー－":
        t = t.replace(ch, "-")
    t = re.sub(r"(?<=[0-9]),(?=[0-9])", "", t)
    return re.sub(r"\s+", " ", t).strip()


def tight(text):
    """空白を落とした形。組や場名は、画面側で間が空いていても拾えるように"""
    return re.sub(r"\s+", "", norm(text))


def verify_text(text, place, rno, combo, yen, units=None, totals=True):
    """確認画面の文字列が、買おうとしているものと一致するか

    画面もネットも要らないので、テストから直接叩ける。これが最後の砦。

    totals=True のときは合計欄も見る。1点ずつ買うので、確認画面はいつも
    「合計ベット数 1ベット / 合計金額 100円」のはず。ここがずれていたら、
    ベットリストに前回の買い残りが混ざっている。押さずに止める。
    """
    spaced, packed = norm(text), tight(text)
    ng = []
    if tight(place) not in packed:
        ng.append(f"場({place})が確認画面に無い")
    if not re.search(rf"(?<![0-9]){rno}(R|レース)", packed):
        ng.append(f"レース番号({rno}R)が確認画面に無い")
    if BET_TYPE and tight(BET_TYPE) not in packed:
        ng.append(f"勝式({BET_TYPE})が確認画面に無い")
    if tight(combo) not in packed:
        ng.append(f"組({combo})が確認画面に無い")
    ok_yen = re.search(rf"(?<![0-9]){yen}(?![0-9])", spaced)
    ok_unit = units is not None and re.search(rf"(?<![0-9]){units} ?口", spaced)
    if not (ok_yen or ok_unit):
        ng.append(f"金額({yen}円)が確認画面に無い")
    if totals:
        if TOTAL_BETS and tight(TOTAL_BETS.format(n=1)) not in packed:
            ng.append("合計が1ベットではない（ベットリストに買い残りがあるかも）")
        if TOTAL_YEN and tight(TOTAL_YEN.format(yen=yen)) not in packed:
            ng.append(f"合計金額が{yen}円ではない")
    return ng


class TelebotePage:
    """1レース1組の投票を、確認画面の照合つきで進める"""

    def __init__(self, page, shot_dir=None, top_url=""):
        self.page = page
        self.shot_dir = shot_dir
        self.top_url = top_url

    # ---- 部品 ------------------------------------------------------------
    def _click(self, selector):
        self.page.wait_for_selector(selector, timeout=TIMEOUT_MS)
        self.page.click(selector)

    def _fill(self, selector, value):
        self.page.wait_for_selector(selector, timeout=TIMEOUT_MS)
        self.page.fill(selector, str(value))

    def _set_lane(self, selector):
        """着順のチェックボックス。check が効かない作りなら click に落とす"""
        self.page.wait_for_selector(selector, timeout=TIMEOUT_MS)
        try:
            self.page.check(selector)
        except Exception:
            self.page.click(selector)

    def _shot(self, b, tag):
        if not self.shot_dir:
            return
        os.makedirs(self.shot_dir, exist_ok=True)
        name = f"{b.date}_{b.jcd}_{b.rno}R_{b.kind}_{b.combo}_{tag}.png"
        self.page.screenshot(path=os.path.join(self.shot_dir, name), full_page=True)

    # ---- 手順 ------------------------------------------------------------
    def open_race(self, b):
        url = (SELECTORS.get("race_url") or "").strip()
        if url:
            self.page.goto(url.format(jcd=b.jcd, rno=b.rno), timeout=TIMEOUT_MS)
        else:
            self._click(_sel("place_link", jcd=b.jcd, place=b.place))
            self._click(_sel("race_link", rno=b.rno))

    def choose_trifecta(self):
        """勝式を3連単にする

        すでに3連単が選ばれていると、押すところが出ない・名前が変わることがある。
        ここでの失敗は見逃して進み、確認画面の「3連単」の照合で拾う。
        """
        for name in ("bet_type_open", "bet_type_trifecta"):
            sel = (SELECTORS.get(name) or "").strip()
            if not sel:
                continue
            try:
                self.page.wait_for_selector(sel, timeout=3000)
                self._set_lane(sel)         # radio も button もこれで押せる
            except Exception:
                pass

    def enter_combo(self, combo):
        parts = [p for p in combo.split("-") if p]
        if len(parts) != 3:
            raise BetAborted(f"3連単の組として読めません: {combo!r}")
        self._set_lane(_sel("lane1", d=parts[0]))
        self._set_lane(_sel("lane2", d=parts[1]))
        self._set_lane(_sel("lane3", d=parts[2]))

    def enter_amount(self, yen):
        """口数（または金額）を入れて、投票へ進む"""
        self._fill(_sel("amount"), units_of(yen))
        add = (SELECTORS.get("add_to_slip") or "").strip()
        if add:
            self._click(add)

    def to_confirm(self):
        self._click(_sel("to_confirm"))
        mark = (SELECTORS.get("confirm_mark") or "").strip() or _sel("confirm_area")
        self.page.wait_for_selector(mark, timeout=TIMEOUT_MS)

    def confirm_text(self):
        """照合に使う文字。買い目の表だけを見て、取れなければ画面全体で見る"""
        for name in ("confirm_area", "confirm_area_fallback"):
            sel = (SELECTORS.get(name) or "").strip()
            if not sel:
                continue
            try:
                text = self.page.inner_text(sel)
            except Exception:
                continue
            if (text or "").strip():
                return text
        raise BetAborted("確認画面の文字が読めません")

    def submit(self, yen):
        """合計金額を打ち直して確定する。押した後で転んだら BetUncertain"""
        total = (SELECTORS.get("total_amount") or "").strip()
        if total:
            self._fill(total, yen)          # ここまでは押していない
        sel = _sel("submit")
        self.page.wait_for_selector(sel, timeout=TIMEOUT_MS)
        try:
            self.page.click(sel)
            done = (SELECTORS.get("done_mark") or "").strip()
            if done:
                self.page.wait_for_selector(done, timeout=TIMEOUT_MS)
        except Exception as e:
            raise BetUncertain(f"投票を押したあたりで失敗: {type(e).__name__}: {e}") from e

    def reset(self):
        """次のレースへ進む前に、分かっている場所へ戻す"""
        if self.top_url:
            self.page.goto(self.top_url, timeout=TIMEOUT_MS)

    def _safe_reset(self):
        """投票が通った後の後始末。ここで転んでも投票の成否は変わらない"""
        try:
            self.reset()
        except Exception:
            pass

    # ---- 本体 ------------------------------------------------------------
    def bet(self, b, yen, live):
        """1点ぶん投票する。押したら True、押さなかったら False

        例外は握りつぶさない。呼び出し側がその周を打ち切る。
        """
        self.open_race(b)
        self.choose_trifecta()
        self.enter_combo(b.combo)
        self.enter_amount(yen)
        self.to_confirm()
        self._shot(b, "confirm")

        units = units_of(yen) if AMOUNT_IN_UNITS else None
        ng = verify_text(self.confirm_text(), b.place, b.rno, b.combo, yen, units)
        if ng:
            self._safe_reset()
            raise BetAborted("確認画面が意図と一致しません: " + " / ".join(ng))

        if not live:
            self._safe_reset()    # dry は確認画面まで。押さない
            return False

        self.submit(yen)          # ここから先の失敗は BetUncertain
        self._safe_reset()        # 後始末で転んでも、投票は通っている
        return True


def units_of(yen):
    """画面に入れる数。口数なら 100円=1口、円ならそのまま"""
    return yen // 100 if AMOUNT_IN_UNITS else yen


def bet(page, b, yen, live, shot_dir=None, top_url=""):
    """auto_bet 本体から呼ぶ入口"""
    return TelebotePage(page, shot_dir=shot_dir, top_url=top_url).bet(b, yen, live)


def open_top(page, url):
    page.goto(url, timeout=TIMEOUT_MS)


def check_logged_in(page):
    """ログイン済みか。logged_in_mark が空なら None（判断しない）"""
    mark = (SELECTORS.get("logged_in_mark") or "").strip()
    if not mark:
        return None
    try:
        page.wait_for_selector(mark, timeout=TIMEOUT_MS)
        return True
    except Exception:
        return False
