#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""telebote_page.py -- テレボート（bu.tbbr.jp）の画面操作だけを閉じ込めたファイル

サイトの作りが変わったとき、直すのがこのファイルだけで済むように、
画面に触るコードはここにしか置きません。

実際に dry で通った流れ（2026-09-19 確認）:

  トップ → 場をクリック（締切がいちばん近いレースが開く）
  → 1着/2着/3着をチェック（#bet1-1 など。実体は隠れた input）
  → 口数を入れる（1口 = 100円）→「ベットリストに追加して投票へ進む」
  → ベットリスト画面で照合 →「次へ」
  → 確認画面で照合 → 合計金額（円）を入れる →「投票」→ 完了
  → 「場を変更して投票（トップへ戻る）」で戻る

このサイトで引っかかったところ:

- URL を直接開くとログインが切れる。ログイン後は goto を使わず、
  画面の中のリンクで移動すること
- ベットリストの件数（赤いバッジ）は文字として読めない。件数ではなく
  画面の中身で確かめること
- ベットリストに買い残りがあると、追加しても確認画面に載らない
- 読み込み中の輪が出ている間はクリックが吸われる。押す前に待つこと
- 入力欄は、クリックしてから入れ、入ったかを読み返すこと

★ログイン情報はここにも他のどこにも書きません。
  dry / live を動かしたときに、開いた Chrome で手でログインします。
"""
import os
import re
import unicodedata

# --------------------------------------------------------------------------
# 画面の場所。codegen の記録から起こしたもの
# --------------------------------------------------------------------------
SELECTORS = {
    # ★レースは必ずクリックで辿る。URL を直接開くとログインが切れる。
    #   下の race_url は、着いたかどうかを URL で確かめるための形の控え
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
    # 口数（1口 = 100円）。|| でどれか。見えている入力欄を順に試す
    "amount": "role=textbox || input[type=text] || input[type=number] "
              "|| input:not([type=hidden])",
    "add_to_slip": "text=ベットリストに追加して投票へ進む",
    "to_confirm": "role=button[name=\"次へ\"]",
    "confirm_mark": "text=投票はまだ完了していません",   # 確認画面に着いた印
    # 照合に使う範囲。表が複数あるので、「合計金額」が載っている表を選ぶ。
    # 見つからなければ画面全体を読む
    "confirm_area": "table",
    "confirm_area_fallback": "body",
    # 確認画面で打ち直す合計金額
    "total_amount": "role=textbox || input[type=text] || input[type=number] "
                    "|| input:not([type=hidden])",
    "submit": "role=button[name=\"投票\"]",
    "done_mark": "text=場を変更して投票",   # 投票完了の印
    # ★ログイン後のトップ。生存確認も投票後の後始末も、必ずここへ戻る。
    #   入口（config.json の telebote_url）はログイン画面なので、
    #   そこへ戻るとログインが切れる
    "home_url": "https://bu.tbbr.jp/top?hatsubaiKbn=0",   # 最後の手段
    # ★画面の中の「トップ」。URL を開くとログインが切れるので、必ずこちらで戻る
    "home_link": "text=トップ",
    # ログアウト避けに押すもの。開き直すより画面の中を動かすほうが安全
    "keepalive_click": "text=開催情報更新",
    # 投票が済んだ画面からトップへ戻るリンク
    "back_to_top": "text=場を変更して投票",
    # ベットリストの残り件数を読むところ（見出しの横に数字が出る）
    "slip_badge": "text=ベットリスト",
    # ★dry のあと、残った買い目を片付けるため。中身は推測なので、
    #   効かなければ手で消してもらう（消せたかは件数で確かめる）
    "slip_open": "text=ベットリスト",
    "slip_clear": ("text=全削除 || text=全て削除 || text=すべて削除 || text=全件削除 "
                   "|| text=クリア"),
    # 全削除のあとに確認が出たら答えるところ
    "slip_clear_ok": "text=はい || text=OK || role=button[name=\"削除\"] || text=削除する",
    # ログイン済みのときだけ出るもの。|| で区切ると、どれか1つ出ていれば良い
    "logged_in_mark": "text=マイページ || text=購入残高 || text=ログアウト",
}

# レース選択まわり。名前が毎回変わるので、正規表現で拾う
RACE_BUTTON = r"^[0-9]+R\s"        # 場の画面の「4R 12:47」
RACE_IN_LIST = r"^{rno}R(\D|$)"    # 一覧の「4R 予選 12:47」

# 確認画面の合計欄の書き方。ここが変わったら直す
CONFIRM_KEY = "合計金額"           # 照合に使う範囲を見分ける目印
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
    def settle(self, timeout=5000):
        """読み込み中の輪が消えるのを待つ。出たままだとクリックが全部吸われる"""
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass

    def _click(self, selector, timeout=TIMEOUT_MS):
        self.settle()
        self.page.wait_for_selector(selector, timeout=timeout)
        self.page.click(selector)
        self.page.wait_for_timeout(300)

    def _click_any(self, selector, timeout=5000):
        """|| で区切った候補を順に試す。どれも押せなければ False"""
        for one in [x.strip() for x in selector.split("||") if x.strip()]:
            try:
                self._click(one, timeout=timeout)
                return True
            except Exception:
                continue
        return False

    def _fill(self, selector, value, what="入力欄"):
        """値を入れて、本当に入ったかを読み返す

        テレボートの金額欄は、クリックしてからでないと受け付けないことがある
        （採取の記録も click() → fill() の順だった）。fill が効かない作りなら
        1文字ずつ打つところまで落とす。入っていなければ止める。
        """
        want = str(value)
        tried = []
        for one in [x.strip() for x in selector.split("||") if x.strip()]:
            try:
                self.page.wait_for_selector(one, timeout=5000)
            except Exception as e:
                tried.append(f"{one}: 出てこない")
                continue
            boxes = self.page.locator(one)
            for i in range(min(boxes.count(), 4)):      # 見えている順に試す
                el = boxes.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    el.click(timeout=2000)
                    el.fill(want, timeout=2000)
                    if self._committed(el, want):
                        return
                    el.fill("")                          # 効かなければ1文字ずつ
                    el.type(want, delay=50)
                    if self._committed(el, want):
                        return
                    tried.append(f"{one}[{i}]: {el.input_value()!r} になった")
                except Exception as e:
                    tried.append(f"{one}[{i}]: {type(e).__name__}")
        raise BetAborted(f"{what}に {want} を入れられません（" + " / ".join(tried) + "）")

    def _set_lane(self, selector, verify=True):
        """チェックを入れる

        テレボートの着順は、見えているマスと実体のチェックボックスが別もので、
        実体のほうは隠れていることがある（採取の記録でも、マスを押してから
        #bet1-1 が check されていた）。Playwright は隠れた要素を押せないので、
        押し方を順に落としていく。最後に、本当に入ったかを確かめる。
        """
        el = self.page.locator(selector).first
        el.wait_for(state="attached", timeout=TIMEOUT_MS)

        ways = []
        ways.append(lambda: el.check(timeout=3000))          # ふつうに
        if selector.startswith("#"):                          # 隠れた input なら
            sid = selector[1:]
            ways.append(lambda: self.page.click(f"label[for='{sid}']", timeout=2000))
        ways.append(lambda: el.check(timeout=2000, force=True))
        ways.append(lambda: el.dispatch_event("click"))       # DOM に直接

        last = None
        for way in ways:
            try:
                way()
            except Exception as e:
                last = e
                continue
            if not verify or self._is_checked(el):
                return
        raise BetAborted(f"{selector} にチェックを入れられません（{last}）")

    def _committed(self, el, want):
        """入れた値を確定させて、残っているか見る

        入れただけでは拾わない作りがあるので、Tab を打って確定させる。
        """
        if (el.input_value() or "").strip() != want:
            return False
        try:
            el.press("Tab")
            self.page.wait_for_timeout(200)
        except Exception:
            pass
        return (el.input_value() or "").strip() == want

    def _is_checked(self, el):
        """入ったかどうか。チェックボックスでなければ確かめようがないので True"""
        try:
            return el.is_checked()
        except Exception:
            return True

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
                f.write(f"題名: {self.page.title()}\n")
                f.write(f"ベットリスト: {slip_left(self.page)} 件\n")
                try:
                    tb = self.page.locator("table")
                    f.write(f"表の数: {tb.count()}\n")
                    for i in range(min(tb.count(), 8)):
                        one = tight(tb.nth(i).inner_text())[:80]
                        f.write(f"  表{i}: {one}\n")
                except Exception as e:
                    f.write(f"表を読めません: {e}\n")
                f.write("\n---- 画面の文字 ----\n")
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

        場を選べば、締切がいちばん近いレースが最初から開く。買うのはたいてい
        その締切間近のレースなので、ふだんはそれで着く。余計な操作は増やさない。

        着いた先が目当てのレースでなかったときだけ、レース選択から選び直す。
        着いたかどうかは URL の jyoCode / raceNo で確かめる。
        """
        open_home(self.page)
        self._click(_sel("place_link", jcd=b.jcd, place=b.place))
        if self.arrived(b):
            return "場を選んだだけ"

        # ここから先は、開いたのが別のレースだったときの立て直し
        print(f"   （{b.place}{b.rno}R ではなく {self.page.url} が開いたので選び直します）")
        try:
            self._open_chooser()
            self._pick_race(b)
            self.page.wait_for_timeout(1000)
            if self.arrived(b):
                return "レース選択から"
        except Exception as e:
            print(f"   （レース選択で失敗: {type(e).__name__}: {e}）")
        self.dump(b, "レース選択")

        # URL を直接開く道は使わない。開くとログインが切れるため
        self._safe_reset()
        raise BetAborted(f"{b.place}{b.rno}R の画面を開けません（いま {self.page.url}）")

    def arrived(self, b, timeout=5000):
        """舟券の画面に着いていて、それが目当てのレースかどうか"""
        return self.on_bet_page(timeout=timeout) and self._is_race(b)

    def on_bet_page(self, timeout=5000):
        mark = (SELECTORS.get("bet_page_mark") or "").strip()
        if not mark:
            return True
        try:
            self.page.wait_for_selector(mark, timeout=timeout)
            return True
        except Exception:
            return False

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

    def fix_bet_type(self):
        """勝式を3連単にし直す

        3連単は最初から選ばれているので、ふだんは触らない（触るほど事故が増える）。
        組を入れられなかったときだけ、ここを通る。
        確認画面でも「3連単」を照合しているので、間違ったまま買うことはない。
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
        try:
            self._put_combo(parts)
        except Exception:
            # 3連単の画面でなかったのかもしれない。直して一度だけやり直す
            self.fix_bet_type()
            self._put_combo(parts)

    def _put_combo(self, parts):
        self._set_lane(_sel("lane1", d=parts[0]))
        self._set_lane(_sel("lane2", d=parts[1]))
        self._set_lane(_sel("lane3", d=parts[2]))

    def enter_amount(self, yen):
        """口数（または金額）を入れて、ベットリストに入れる"""
        self._fill(_sel("amount"), units_of(yen), "口数の欄")
        add = (SELECTORS.get("add_to_slip") or "").strip()
        if add:
            self._click(add)
            self.settle()
            # ベットリスト画面に着いたか（「次へ」が出ているか）
            try:
                self.page.wait_for_selector(_sel("to_confirm"), timeout=TIMEOUT_MS)
            except Exception:
                raise BetAborted("ベットリストの画面に進めませんでした")

    def check_slip(self, b, yen):
        """ベットリスト画面の中身を照合する

        確認画面の1つ手前。ここで見ておけば、買い残りが混ざっていることにも、
        入っていないことにも、進む前に気づける。
        """
        text = self.page.inner_text("body")
        units = units_of(yen) if AMOUNT_IN_UNITS else None
        ng = verify_text(text, b.place, b.rno, b.combo, yen, units)
        if ng:
            self.dump(b, "ベットリスト")
            raise BetAborted("ベットリストが意図と一致しません: " + " / ".join(ng)
                             + f"｜読んだ文字: {tight(text)[:120]}")

    def to_confirm(self):
        self._click(_sel("to_confirm"))
        mark = (SELECTORS.get("confirm_mark") or "").strip() or _sel("confirm_area")
        self.page.wait_for_selector(mark, timeout=TIMEOUT_MS)

    def confirm_text(self):
        """照合に使う文字を取る

        この画面には表が複数あるので、最初の表を読むと買い目の表ではない
        ことがある（それで照合が全部外れていた）。「合計金額」が載っている
        ものを選び、見つからなければ画面全体を読む。
        """
        sel = (SELECTORS.get("confirm_area") or "").strip()
        if sel:
            try:
                boxes = self.page.locator(sel)
                for i in range(min(boxes.count(), 8)):
                    text = boxes.nth(i).inner_text()
                    if CONFIRM_KEY in tight(text or ""):
                        return text
            except Exception:
                pass
        fallback = (SELECTORS.get("confirm_area_fallback") or "body").strip()
        text = self.page.inner_text(fallback)
        if not (text or "").strip():
            raise BetAborted("確認画面の文字が読めません")
        return text

    def fill_total(self, yen):
        """確認画面の合計金額を入れる。まだ押さない

        dry でもここまでやる。入れずに止めると、live で初めて通る手が
        残ってしまい、確かめたことにならない。
        """
        total = (SELECTORS.get("total_amount") or "").strip()
        if total:
            self._fill(total, yen, "合計金額の欄")

    def submit(self):
        """確定を押す。押した後で転んだら BetUncertain"""
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
        # ★先にベットリストを空にしておくこと。残っていると、追加しても
        #   確認画面に載らない（合計ベット数が空・合計金額0円になる）。
        #   ただしバッジは読めないことが多いので、読めたときだけ見る
        left = slip_left(self.page)
        if left:
            raise BetAborted(
                f"ベットリストに {left} 件残っています。テレボートの画面で"
                "先に空にしてください（残っていると確認画面に載りません）")

        try:
            self.open_race(b)
            self.enter_combo(b.combo)  # 勝式は触らない。3連単は最初から選ばれている
            self.enter_amount(yen)
            self.check_slip(b, yen)    # 確認画面の手前で、ここでも照合する
            self.to_confirm()
        except Exception:
            self.dump(b, "途中で失敗")   # 何が出ていたかを残す
            raise
        units = units_of(yen) if AMOUNT_IN_UNITS else None
        text = self.confirm_text()
        ng = verify_text(text, b.place, b.rno, b.combo, yen, units)
        if ng:
            self.dump(b, "照合できず")      # 何が出ていたかを残す
            self._safe_reset()
            packed = tight(text)
            if TOTAL_BETS.split("{")[0] not in packed and CONFIRM_KEY not in packed:
                raise BetAborted(
                    "確認画面に買い目が1件も載っていません"
                    "（ベットリストに入っていないか、読む場所が違う）"
                    f"｜読んだ文字: {packed[:120]}")
            raise BetAborted("確認画面が意図と一致しません: " + " / ".join(ng)
                             + f"｜読んだ文字: {packed[:120]}")

        try:
            self.fill_total(yen)   # 合計金額まで入れる。押すのはこの次
        except Exception:
            self.dump(b, "合計金額")
            raise
        self._shot(b, "confirm")   # live が押す直前と同じ画面を残す

        if not live:
            self._safe_reset()    # dry はここまで。押さない
            return False

        self.submit()             # ここから先の失敗は BetUncertain
        self._safe_reset()        # 後始末で転んでも、投票は通っている
        return True


def units_of(yen):
    """画面に入れる数。口数なら 100円=1口、円ならそのまま"""
    return yen // 100 if AMOUNT_IN_UNITS else yen


def bet(page, b, yen, live, shot_dir=None, top_url=""):
    """auto_bet 本体から呼ぶ入口"""
    return TelebotePage(page, shot_dir=shot_dir, top_url=top_url).bet(b, yen, live)


SLIP_TOTAL_RE = re.compile(r"合計ベット数([0-9]+)ベット")


def slip_count_in_text(text, url=""):
    """画面の文字から、ベットリストの件数を読む。読めなければ None

    画面もネットも要らないので、テストから直接叩ける。

    ★ヘッダーの赤いバッジは数字が文字として出てこない（2026-09-22 実機で確認。
      inner_text にも locator にも「4」が現れなかった）。読めるのは
      ベットリスト画面の「合計ベット数 N ベット」だけ。
    ★ベットリスト画面なのに合計が無ければ、空（0件）。
      それ以外の画面では None（＝分からない）を返すこと。0 と決めつけると、
      入っているのに「空だ」と誤判定して、買い残りの上に積み増す。
    """
    m = SLIP_TOTAL_RE.search(tight(text or ""))
    if m:
        return int(m.group(1))
    if "betlist" in (url or "").lower():
        return 0
    return None


def slip_left(page):
    """ベットリストに残っている件数。読めなければ None

    ★2026-09-22: ヘッダーのバッジを読む作りだったが、実機では数字が
      文字として取れず、いつも None を返していた。その None を
      clear_slip が「空」と読んで何もせず True を返していたため、
      失敗するたびに買い目が積み上がった（江戸川6R で4件）。
      いまはベットリスト画面の「合計ベット数」を先に見る。
    """
    try:
        n = slip_count_in_text(page.inner_text("body"), getattr(page, "url", "") or "")
    except Exception:
        n = None
    if n is not None:
        return n
    sel = (SELECTORS.get("slip_badge") or "").strip()
    if not sel:
        return None
    best = None
    try:
        boxes = page.locator(sel)
        for i in range(min(boxes.count(), 6)):
            m = re.search(r"([0-9]+)", tight(boxes.nth(i).inner_text()))
            if m:
                best = max(best or 0, int(m.group(1)))
    except Exception:
        return None
    return best


def clear_slip(page):
    """ベットリストを空にする

    dry は投票を押さないので、試すたびに1件残る。live でも、ベットリストに
    入れたあとで失敗すると同じように1件残る。残ったまま次の周でもう一度
    追加すると「合計ベット数2ベット」になり、照合が通らず永久に買えない。

    消し方は推測なので、消せたかどうかは件数で確かめる。
    駄目なら False を返し、手で消してもらう。
    """
    # ★None（分からない）を「空」と読んではいけない。分からないなら押しに行く
    if slip_left(page) == 0:
        return True
    for name in ("slip_open", "slip_clear", "slip_clear_ok"):
        sel = (SELECTORS.get(name) or "").strip()
        if not sel:
            continue
        for one in [x.strip() for x in sel.split("||") if x.strip()]:
            try:
                page.wait_for_selector(one, timeout=3000)
                page.click(one)
                page.wait_for_timeout(700)
                break
            except Exception:
                continue
    # ★ここでも None は「消せた」ではない。分からないものは False にして、
    #   手で確かめてもらう
    return slip_left(page) == 0


def open_top(page, url):
    """入口（ログイン画面）を開く。起動時に一度だけ"""
    page.goto(url, timeout=TIMEOUT_MS)


def open_home(page):
    """ログイン後のトップへ戻る

    ★URL を開くとログインが切れるサイトなので、まず画面の中のリンクを押す。
      押せないときだけ URL を開く（最後の手段）。
    """
    link = (SELECTORS.get("home_link") or "").strip()
    if link:
        try:
            page.wait_for_selector(link, timeout=5000)
            page.click(link)
            page.wait_for_timeout(500)
            return "リンク"
        except Exception:
            pass
    url = (SELECTORS.get("home_url") or "").strip()
    if url:
        page.goto(url, timeout=TIMEOUT_MS)
        return "URL"
    page.reload(timeout=TIMEOUT_MS)
    return "読み込み直し"


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
