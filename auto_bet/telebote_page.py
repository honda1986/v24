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
    # ★レースの開き方。URL を直接開くとトップへ戻されることがあるので、
    #   「トップ → 場を選ぶ → （必要ならレースを選ぶ）」と人と同じ順に辿る。
    #   URL は場を選んだ後でだけ使う
    "race_url": "https://bu.tbbr.jp/bet?hatsubaiKbn=0&jyoCode={jcd:02d}&raceNo={rno:02d}",
    "place_link": "text={place}",          # トップの場のカード
    # 場の画面で、レース選択を開くところ。ボタンの名前は「4R 12:47」のように
    # そのときの対象レースで変わるので、名前は下の正規表現で拾う。ここは控え
    "race_chooser": "text=/^[0-9]+R\\s+[0-9]+:/ || role=button[name=\"レース選択\"]",
    # レース一覧の中の、買いたいレース。名前は「4R 予選 12:47」のような形
    "race_in_modal": "[data-testid=modal] >> text=/^{rno}R/",   # 控え
    "bet_page_mark": "[id^='bet1-']",      # 舟券の画面に着いた印（着順のチェックボックス）
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
    # ★ログイン後のトップ。生存確認も投票後の後始末も、必ずここへ戻る。
    #   入口（config.json の telebote_url）はログイン画面なので、
    #   そこへ戻るとログインが切れる
    "home_url": "https://bu.tbbr.jp/top?hatsubaiKbn=0",
    # ログアウト避けに押すもの。開き直すより画面の中を動かすほうが安全
    "keepalive_click": "text=開催情報更新",
    # 投票が済んだ画面からトップへ戻るリンク
    "back_to_top": "text=場を変更して投票",
    # ログイン済みのときだけ出るもの。|| で区切ると、どれか1つ出ていれば良い
    "logged_in_mark": "text=マイページ || text=購入残高 || text=ログアウト",
}

# レース選択まわり。名前が毎回変わるので、正規表現で拾う
RACE_BUTTON = r"^[0-9]+R\s"        # 場の画面の「4R 12:47」
RACE_IN_LIST = r"^{rno}R(\D|$)"    # 一覧の「4R 予選 12:47」

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


# 空だと dry / live が始められないもの
REQUIRED = ("place_link", "lane1", "lane2", "lane3", "amount",
            "to_confirm", "confirm_area", "submit")


def missing_selectors():
    """埋まっていない SELECTORS を並べる（起動時に見て、動く前に止めるため）"""
    miss = [k for k in REQUIRED if not (SELECTORS.get(k) or "").strip()]
    if not (SELECTORS.get("race_url") or "").strip() \
            and not (SELECTORS.get("race_in_modal") or "").strip():
        miss.append("race_url か race_in_modal のどちらか")
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
    def _click(self, selector, timeout=TIMEOUT_MS):
        self.page.wait_for_selector(selector, timeout=timeout)
        self.page.click(selector)

    def _click_any(self, selector, timeout=5000):
        """|| で区切った候補を順に試す。どれも押せなければ False"""
        for one in [x.strip() for x in selector.split("||") if x.strip()]:
            try:
                self._click(one, timeout=timeout)
                return True
            except Exception:
                continue
        return False

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

    def dump(self, b, tag):
        """いまの画面を残す。何が出ているか分からないと直しようがない

        スクリーンショットと、URL・画面の文字を shots に置く。
        """
        if not self.shot_dir:
            return
        os.makedirs(self.shot_dir, exist_ok=True)
        base = os.path.join(self.shot_dir, f"NG_{b.date}_{b.place}{b.rno}R_{tag}")
        try:
            self.page.screenshot(path=base + ".png", full_page=True)
        except Exception:
            pass
        try:
            text = self.page.inner_text("body")
        except Exception as e:
            text = f"（画面の文字を読めません: {e}）"
        try:
            with open(base + ".txt", "w", encoding="utf-8") as f:
                f.write(f"URL: {self.page.url}\n")
                f.write(f"題名: {self.page.title()}\n\n")
                f.write(text[:4000])
        except Exception:
            pass

    def _shot(self, b, tag):
        if not self.shot_dir:
            return
        os.makedirs(self.shot_dir, exist_ok=True)
        name = f"{b.date}_{b.jcd}_{b.rno}R_{b.kind}_{b.combo}_{tag}.png"
        self.page.screenshot(path=os.path.join(self.shot_dir, name), full_page=True)

    # ---- 手順 ------------------------------------------------------------
    def open_race(self, b):
        """レースの舟券画面まで行く

        URL を直接開くとトップへ戻されることがある（場を選んでいない状態だと
        弾かれる）。人と同じ順に辿るやり方から順に試し、着けたかどうかを
        着順のチェックボックスが出ているかで確かめる。
        """
        tried = []
        # URL を直接開くのは最後。クリックで辿るほうが弾かれにくい
        for how in (self._by_modal, self._by_place_then_url, self._by_url):
            try:
                how(b)
                if self.on_bet_page() and self._is_race(b):
                    print(f"   （{b.place}{b.rno}R は {how.__name__} で開きました）")
                    return how.__name__
                tried.append(f"{how.__name__}: 目当ての画面に着かなかった（{self.page.url}）")
            except Exception as e:
                tried.append(f"{how.__name__}: {type(e).__name__}: {e}")
            self.dump(b, how.__name__)   # 何が出ていたかを残す
            self._safe_reset()           # トップへ戻してから次を試す
        raise BetAborted(f"{b.place}{b.rno}R の画面を開けません（" + " / ".join(tried) + "）")

    def on_bet_page(self, timeout=5000):
        mark = (SELECTORS.get("bet_page_mark") or "").strip()
        if not mark:
            return True
        try:
            self.page.wait_for_selector(mark, timeout=timeout)
            return True
        except Exception:
            return False

    def _by_place_then_url(self, b):
        """トップで場を選んでから、URL でレースへ。いちばん短い道"""
        open_home(self.page)
        self._click(_sel("place_link", jcd=b.jcd, place=b.place))
        url = (SELECTORS.get("race_url") or "").strip()
        if not url:
            raise BetAborted("race_url が空です")
        self.page.goto(url.format(jcd=b.jcd, rno=b.rno), timeout=TIMEOUT_MS)

    def _by_modal(self, b):
        """場を選び、レース選択を開いて、その中から選ぶ。人の操作そのまま"""
        open_home(self.page)
        self._click(_sel("place_link", jcd=b.jcd, place=b.place))
        if self.on_bet_page(timeout=3000) and self._is_race(b):
            return                      # 場を選んだだけで目当てのレースだった
        self._open_chooser()
        self._pick_race(b)
        self.page.wait_for_timeout(1000)    # サイト側の遷移を待つ

    def _open_chooser(self):
        """レース選択を開く。ボタンの名前は「4R 12:47」のように毎回変わる"""
        try:
            self.page.get_by_role(
                "button", name=re.compile(RACE_BUTTON)).first.click(timeout=5000)
            return True
        except Exception:
            return self._click_any((SELECTORS.get("race_chooser") or "").strip())

    def _pick_race(self, b):
        """一覧から目当てのレースを選ぶ

        一覧はチェックボックスで、いま対象のレースは最初から入っている。
        押して切り替えるのではなく check で入れる（入っていれば何もしない）。
        """
        try:
            self.page.get_by_role(
                "checkbox", name=re.compile(RACE_IN_LIST.format(rno=b.rno))
            ).first.check(timeout=5000)
            return
        except Exception:
            pass
        self._set_lane(_sel("race_in_modal", rno=b.rno))

    def _is_race(self, b):
        """いま開いている画面が、目当てのレースかどうか

        URL に raceNo が入っているので、まずそれで見る。
        無ければ画面の文字で見る（こちらは当てにならないので控え）。
        """
        url = self.page.url or ""
        m = re.search(r"raceNo=0*([0-9]+)", url)
        if m:
            j = re.search(r"jyoCode=0*([0-9]+)", url)
            if j and int(j.group(1)) != b.jcd:
                return False
            return int(m.group(1)) == b.rno
        try:
            return bool(re.search(rf"(?<![0-9]){b.rno}R", tight(self.page.inner_text("body"))))
        except Exception:
            return False

    def _by_url(self, b):
        """URL を直接。これが通るならいちばん確実なので、最後に残しておく"""
        url = (SELECTORS.get("race_url") or "").strip()
        if not url:
            raise BetAborted("race_url が空です")
        self.page.goto(url.format(jcd=b.jcd, rno=b.rno), timeout=TIMEOUT_MS)

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
        """次のレースへ進む前に、ログイン後のトップへ戻す

        画面の中のリンクで戻るほうが、URLを開き直すよりログイン状態に触らない。
        入口のURL（ログイン画面）へは戻さない。
        """
        back = (SELECTORS.get("back_to_top") or "").strip()
        if back:
            try:
                self.page.wait_for_selector(back, timeout=5000)
                self.page.click(back)
                return
            except Exception:
                pass
        open_home(self.page)

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
    """入口（ログイン画面）を開く。起動時に一度だけ"""
    page.goto(url, timeout=TIMEOUT_MS)


def open_home(page):
    """ログイン後のトップを開く

    home_url が空なら、いまの画面を読み込み直すだけにする。
    """
    url = (SELECTORS.get("home_url") or "").strip()
    if url:
        page.goto(url, timeout=TIMEOUT_MS)
    else:
        page.reload(timeout=TIMEOUT_MS)


def keepalive(page):
    """ログアウトされないように画面を動かす

    「一定時間操作がない場合、自動的にログアウトします」と画面に出ている。
    ページを開き直すよりも、トップの「開催情報更新」を押すほうが、
    ログイン状態に触らずに「操作した」ことにできる。
    押せる場所に居なければ、トップを開き直す。
    """
    sel = (SELECTORS.get("keepalive_click") or "").strip()
    if sel:
        try:
            page.wait_for_selector(sel, timeout=5000)
            page.click(sel)
            page.wait_for_timeout(1000)
            return "押した"
        except Exception:
            pass
    open_home(page)
    return "開き直した"


def check_logged_in(page, timeout=5000):
    """ログイン済みか。logged_in_mark が空なら None（判断しない）

    || で区切られた候補のどれか1つでも出ていればログイン済みとみなす。
    画面の作りが変わって印が見つからないこともあるので、
    False を「確実にログアウト」と決めつけず、人に聞く側で受け止めること。
    """
    marks = [m.strip() for m in (SELECTORS.get("logged_in_mark") or "").split("||")]
    marks = [m for m in marks if m]
    if not marks:
        return None
    for m in marks:
        try:
            page.wait_for_selector(m, timeout=timeout)
            return True
        except Exception:
            continue
    return False
