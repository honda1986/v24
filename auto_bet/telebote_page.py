#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""telebote_page.py -- テレボートの画面操作だけを閉じ込めたファイル

★セレクタは空のまま置いてあります。ご自身で採取して埋めてください。
  サイトの作りが変わったとき、直すのがこのファイルだけで済むように、
  画面に触るコードはここにしか置きません。

  pip install playwright
  playwright install chromium
  playwright codegen --channel=chrome <テレボートのURL>

  1. codegen を起動する
  2. 手でログインする
  3. 適当なレースで100円ぶんの舟券を実際に1つ買ってみる（3連単1点）
  4. 表示されたコードから、下の SELECTORS に対応するものを写す

最後の砦は verify()。確認画面に出ている 場・R・組・金額 をコードで読み返し、
自分の意図と一致しなければ押さずに中止します。ここだけは必ず動かしてください。
"""
import re
import unicodedata

# --------------------------------------------------------------------------
# ここを埋める。空のまま dry / live を動かすと、その場で止まって理由を出します。
# --------------------------------------------------------------------------
SELECTORS = {
    # 場とレースを開く。URL で直接開けるならこの型を書く（{jcd} {rno} が入る）。
    # 例: "https://.../bet/race?jcd={jcd}&rno={rno}"
    # URL で開けないなら空のままにして、代わりに place_link / race_link を埋める。
    "race_url": "",
    "place_link": "",        # 場を選ぶリンク。{jcd} {place} が使える
    "race_link": "",         # レースを選ぶリンク。{rno} が使える
    "trifecta_tab": "",      # 「3連単」を選ぶところ
    "lane1": "",             # 1着の入力（select / ボタン どちらでも可）
    "lane2": "",             # 2着
    "lane3": "",             # 3着
    "amount": "",            # 金額（または口数）の入力
    "add_to_slip": "",       # 「セット」「リストに追加」など。無ければ空でよい
    "to_confirm": "",        # 「投票」＝確認画面へ進むボタン
    "confirm_area": "",      # 確認画面のうち、場・R・組・金額が載っている範囲
    "submit": "",            # 確認画面の最終確定ボタン（live でしか押さない）
    "done_mark": "",         # 投票完了を示す要素
}

# 金額欄が「口数（100円＝1口）」なら True、「円」そのままなら False
AMOUNT_IN_UNITS = False

# 待ち時間は固定秒ではなく、要素が出るのを待つ
TIMEOUT_MS = 20000


class SelectorNotSet(Exception):
    """SELECTORS が埋まっていない"""


class BetAborted(Exception):
    """画面が想定と違う。この周は打ち切る"""


def _sel(name, **fmt):
    v = (SELECTORS.get(name) or "").strip()
    if not v:
        raise SelectorNotSet(
            f"telebote_page.py の SELECTORS['{name}'] が空です。\n"
            "  playwright codegen --channel=chrome <テレボートのURL>\n"
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


def verify_text(text, place, rno, combo, yen):
    """確認画面の文字列が、買おうとしているものと一致するか

    画面もネットも要らないので、テストから直接叩ける。
    金額だけは空白を残したまま見る（組の数字と地続きに読めてしまうため）。
    """
    spaced, packed = norm(text), tight(text)
    ng = []
    if tight(place) not in packed:
        ng.append(f"場({place})が確認画面に無い")
    if not re.search(rf"(?<![0-9]){rno}(R|レース)", packed):
        ng.append(f"レース番号({rno}R)が確認画面に無い")
    if tight(combo) not in packed:
        ng.append(f"組({combo})が確認画面に無い")
    if not re.search(rf"(?<![0-9]){yen}(?![0-9])", spaced):
        ng.append(f"金額({yen}円)が確認画面に無い")
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

    def _set_lane(self, selector, digit):
        """着順の入力。select でもボタンでも動くように順に試す"""
        self.page.wait_for_selector(selector, timeout=TIMEOUT_MS)
        el = self.page.locator(selector)
        tag = (el.first.evaluate("e => e.tagName") or "").lower()
        if tag == "select":
            el.first.select_option(digit)
        elif tag in ("input", "textarea"):
            el.first.fill(digit)
        else:
            el.first.click()

    def _shot(self, b, tag):
        if not self.shot_dir:
            return
        import os
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
        self._click(_sel("trifecta_tab"))

    def enter_combo(self, combo):
        parts = [p for p in combo.split("-") if p]
        if len(parts) != 3:
            raise BetAborted(f"3連単の組として読めません: {combo!r}")
        self._set_lane(_sel("lane1"), parts[0])
        self._set_lane(_sel("lane2"), parts[1])
        self._set_lane(_sel("lane3"), parts[2])

    def enter_yen(self, yen):
        value = yen // 100 if AMOUNT_IN_UNITS else yen
        sel = _sel("amount")
        self.page.wait_for_selector(sel, timeout=TIMEOUT_MS)
        self.page.fill(sel, str(value))
        add = (SELECTORS.get("add_to_slip") or "").strip()
        if add:
            self._click(add)

    def to_confirm(self):
        self._click(_sel("to_confirm"))
        self.page.wait_for_selector(_sel("confirm_area"), timeout=TIMEOUT_MS)

    def confirm_text(self):
        return self.page.inner_text(_sel("confirm_area"))

    def submit(self):
        self._click(_sel("submit"))
        done = (SELECTORS.get("done_mark") or "").strip()
        if done:
            self.page.wait_for_selector(done, timeout=TIMEOUT_MS)

    def reset(self):
        """次のレースへ進む前に、分かっている場所へ戻す"""
        if self.top_url:
            self.page.goto(self.top_url, timeout=TIMEOUT_MS)

    # ---- 本体 ------------------------------------------------------------
    def bet(self, b, yen, live):
        """1点ぶん投票する。押したら True、押さなかったら False

        例外は握りつぶさない。呼び出し側がその周を打ち切る。
        """
        self.open_race(b)
        self.choose_trifecta()
        self.enter_combo(b.combo)
        self.enter_yen(yen)
        self.to_confirm()
        self._shot(b, "confirm")

        ng = verify_text(self.confirm_text(), b.place, b.rno, b.combo, yen)
        if ng:
            self.reset()
            raise BetAborted("確認画面が意図と一致しません: " + " / ".join(ng))

        if not live:
            self.reset()          # dry は確認画面まで。押さない
            return False

        self.submit()
        self.reset()
        return True


def bet(page, b, yen, live, shot_dir=None, top_url=""):
    """auto_bet 本体から呼ぶ入口"""
    return TelebotePage(page, shot_dir=shot_dir, top_url=top_url).bet(b, yen, live)
