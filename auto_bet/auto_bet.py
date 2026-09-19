#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auto_bet.py -- v24 の history.json を見て、テレボートに自動投票する

  python auto_bet.py --mode login   Chrome を開いて止まる。手でログインする
  python auto_bet.py --mode check   ブラウザを開かず、いま買うべきレースを並べるだけ
  python auto_bet.py --mode dry     ブラウザを開き、確認画面まで進んで押さない
  python auto_bet.py --mode live    実際に投票する（確認フラグが true のときだけ）

★既定のモードはありません。--mode は必ず自分で指定します。
★いきなり live にしないこと。check を1週間 → dry を1週間 → live で1日1レース。

予想側（GitHub Actions / v24）はいっさい触りません。history.json を読むだけです。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import betlog                       # noqa: E402
import browser                      # noqa: E402
import config as config_mod         # noqa: E402
import history_source               # noqa: E402
import selector                     # noqa: E402
import telebote_page                # noqa: E402
from bet_store import BetDoneCorrupt, BetStore       # noqa: E402
from jst import date_str, minutes_to_close, now      # noqa: E402

MODES = ("login", "check", "dry", "live")

TERMS_NG = """live は起動できません。
config.json の i_have_read_the_terms が false のままです。

テレボートの『電話投票に関する約定』を、自分で読むこと。
自動操作の扱いはそこに書かれています。読んで、問題ないと自分で判断したときだけ
true にしてください。判断できないなら false のままで構いません。
dry モードなら、投票を押す直前まで全部動きます。"""


class Runner:
    """1周ぶんの流れ。画面操作は bet_fn として外から差し込む（テストは偽物を渡す）"""

    def __init__(self, cfg, store, mode, log, bet_fn=None, keepalive_fn=None,
                 fetch_fn=None, now_fn=None):
        self.cfg = cfg
        self.store = store
        self.mode = mode
        self.log = log
        self.bet_fn = bet_fn
        self.keepalive_fn = keepalive_fn
        self.fetch_fn = fetch_fn or (lambda url: history_source.fetch(url))
        self.now_fn = now_fn or now
        self.stop_path = cfg.path("stop_file")
        self.halt_reason = ""
        self._dry_seen = set()
        self._last_touch = None

    def stopped(self):
        return os.path.exists(self.stop_path)

    def cycle(self):
        """1周まわす。"stop"（止める） / "ok"（続ける） / "abort"（この周は打ち切り）"""
        if self.stopped():
            return "stop"

        history, why = self.fetch_fn(self.cfg.history_url)
        if history is None:
            # ネット断や push 遅れ。その周は何もせず次へ。落ちない
            self.log.event("見送った", f"history.json を取れず（{why}）")
            return "ok"

        at = self.now_fn()
        today = date_str(at)
        day = history_source.pick_day(history, today)   # 今日のぶん以外は捨てる
        spent = self.store.spent_on(today)
        res = selector.select(day, self.store.keys(), spent, self.cfg, at)

        for w in res.warnings:
            self.log.event("見送った", w)

        # 何も無い周でも1行は出す。黙っていると、止まっているのか
        # 買い目が無いのか分からない
        n_obi, n_ana, nxt = selector.summary(day, self.cfg, at)
        kinds = f"帯{n_obi}" + (f"・穴{n_ana}" if self.cfg.buy_ana else "")
        self.log.event("見た", f"今日 {kinds} レース / いま投票できる組 "
                               f"{len(res.bets)}件 / {nxt}")
        if not res.bets:
            return self._keepalive(at)

        for b in res.bets:
            if self.stopped():
                return "stop"

            if self.mode == "check":
                self.log.bet(b, "買うべき", f"（check なので投票しません 使用済み {spent}円）")
                continue

            if self.mode == "dry" and b.key in self._dry_seen:
                continue            # dry は同じ組を何周も繰り返さない

            # 念のためもう一度見る。選んでから押すまでの間に時間が経っている
            if self.store.has(b.key):
                continue
            left = minutes_to_close(b.date, b.close, self.now_fn())
            if left is None or left < self.cfg.close_min_minutes:
                self.log.bet(b, "見送った",
                             f"押す前に締切が近づいた（あと{left:.1f}分）"
                             if left is not None else "締切が読めない")
                continue

            try:
                pressed = self.bet_fn(b, b.yen, self.mode == "live")
            except telebote_page.BetUncertain as e:
                # 押した後で転んだ。通ったか分からないので、押していない扱いにしない
                return self._uncertain(b, e)
            except Exception as e:
                # 画面が中途半端なまま次のレースへ進むと、違うレースに投票する事故になる
                self.log.bet(b, "失敗", f"{type(e).__name__}: {e} ★手で確認してください")
                return "abort"

            if self.mode == "dry":
                self._dry_seen.add(b.key)
                self.log.bet(b, "見送った", "確認画面まで（押していません）")
                continue

            if not pressed:
                self.log.bet(b, "見送った", "投票していません")
                continue

            # 押せたら、その場で即書く。まとめて最後に書かない
            try:
                self.store.record(b, self.mode)
            except Exception as e:
                self.log.bet(b, "失敗", f"投票は通りましたが記録できません（{e}）。"
                                        "★手で確認してください。止めます")
                return "halt"
            spent += b.yen
            self._last_touch = self.now_fn()
            self.log.bet(b, "投票した", f"当日計 {spent}円")

        return "ok"

    def _keepalive(self, at):
        """買い目が無い時間が続くとテレボートからログアウトさせられる

        「一定時間操作がない場合、自動的にログアウトします」と画面に出ている。
        たまにトップを開き直して、ログインが生きているかも見る。
        """
        if not self.keepalive_fn:
            return "ok"
        every = self.cfg.keepalive_minutes
        if not every:                     # 0 なら開き直さない
            return "ok"
        if self._last_touch is not None:
            if (at - self._last_touch).total_seconds() < every * 60:
                return "ok"
        self._last_touch = at
        try:
            alive = self.keepalive_fn()
        except Exception as e:
            self.log.event("見送った", f"画面を開き直せません（{type(e).__name__}: {e}）")
            return "ok"
        if alive is False:
            self.halt_reason = ("★ログインが切れたまま入り直せませんでした。"
                                "Chrome で手でログインしてから、動かし直してください")
            return "halt"
        return "ok"

    def _uncertain(self, b, e):
        """押した後で失敗したとき。投票済みとして記録し、動作を止める

        次の周で「まだ買っていない」と見なして買い直すのがいちばん危ない。
        買えていなかった場合は1点買い逃すだけで済む。
        """
        try:
            self.store.record(b, self.mode, note=f"要確認（{e}）")
            note = "投票済みとして記録しました"
        except Exception as e2:
            note = f"★記録もできませんでした（{e2}）。次に動かす前に bet_done.json を直すこと"
        self.log.bet(b, "失敗", f"{e} ★手で確認してください（{note}）。止めます")
        return "halt"

    def loop(self, once=False):
        self.log.event("開始", f"{self.mode} / {self.cfg.poll_seconds}秒おき / "
                               f"止めるには {self.stop_path} を作るか Ctrl+C")
        while True:
            state = self.cycle()
            if state == "stop":
                self.log.event("終了", f"{self.stop_path} があるので止めます")
                return 0
            if state == "halt":
                self.log.event("終了", self.halt_reason or
                               "★投票の結果が分からないので止めました。"
                               "テレボートの投票履歴を見て確認してください")
                return 4
            if state == "abort":
                self.log.event("打ち切り", "この周は途中で止めました。次の周へ")
            if once:
                return 0
            for _ in range(self.cfg.poll_seconds):
                if self.stopped():
                    break
                time.sleep(1)


def run_login(cfg, log):
    if not cfg.telebote_url:
        print("config.json の telebote_url が空です。テレボートのURLを入れてください。")
        return 2
    with browser.open_context(cfg) as (_ctx, page):
        page.goto(cfg.telebote_url)
        log.event("ログイン待ち", cfg.telebote_url)
        print("\nこの Chrome で手でログインしてください。")
        print("加入者番号・暗証番号は保存しません。")
        print("★テレボートは Chrome を閉じるとログインが切れます。")
        print("  そのため、普段は login を使わず、dry / live を動かしたときに")
        print("  開いた Chrome でログインしてください（最初に聞きます）。")
        print(f"プロファイル: {cfg.path('profile_dir')}")
        try:
            input("\n終わったら Enter を押してください（Chrome を閉じます）... ")
        except (KeyboardInterrupt, EOFError):
            print()
    log.event("終了", "login")
    return 0


def make_bet_fn(cfg, page):
    shot_dir = cfg.path("shot_dir")
    def bet_fn(b, yen, live):
        return telebote_page.bet(page, b, yen, live,
                                 shot_dir=shot_dir, top_url=cfg.telebote_url)
    return bet_fn


def make_keepalive_fn(cfg, page, log):
    def keepalive_fn():
        how = telebote_page.keepalive(page)     # 「開催情報更新」を押す
        if telebote_page.check_logged_in(page) is not False:
            log.event("見た", f"ログイン維持（{how}）")
            return True
        log.event("見送った", "★ログインが切れました。手でログインし直してください")
        return ensure_logged_in(cfg, page)
    return keepalive_fn


def ensure_logged_in(cfg, page, tries=2):
    """ログインを確かめ、切れていたら、開いている Chrome で手でログインしてもらう

    テレボートは Chrome を閉じるとログインが切れる（セッションが残らない）。
    だから login モードで入れておくことはできず、ここで入ってもらって、
    同じ画面のまま投票へ進む。

    印が見つからないだけの可能性もあるので、何度か聞いたら人の判断を通す。
    無人で動かしているとき（画面から入力できないとき）は False を返して止める。
    """
    for i in range(tries):
        if telebote_page.check_logged_in(page) is not False:
            return True
        if not sys.stdin or not sys.stdin.isatty():
            return False                      # 無人。勝手に進まない
        print("\nログインが確認できません。")
        print("いま開いている Chrome で、手でログインしてください。")
        print("★この Chrome は閉じないでください（閉じるとログインが切れます）")
        if i == tries - 1:
            print("（ログイン済みならそのまま Enter。このまま進みます）")
        try:
            input("終わったら Enter を押してください（やめるときは Ctrl+C）... ")
        except EOFError:
            return False
        telebote_page.open_home(page)         # ログイン後のトップで確かめる
    return True                               # 人が「入っている」と言うなら従う


def main(argv=None):
    ap = argparse.ArgumentParser(description="v24 → テレボート 自動投票")
    ap.add_argument("--mode", required=True, choices=MODES,
                    help="login / check / dry / live（既定はありません）")
    ap.add_argument("--config", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.json"))
    ap.add_argument("--once", action="store_true", help="1周だけ動かして終わる")
    args = ap.parse_args(argv)

    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as e:
        print(f"設定が読めません: {e}")
        return 2
    for k in cfg.unknown_keys:
        print(f"（config.json の {k} は使っていません）")

    if args.mode == "live" and not cfg.i_have_read_the_terms:
        print(TERMS_NG)
        return 2

    log = betlog.Log(cfg.path("log_path"), args.mode)

    if args.mode == "login":
        try:
            return run_login(cfg, log)
        except browser.BrowserUnavailable as e:
            print(e)
            return 2

    # 起動時に必ず読む。壊れていたら空で続行せず、止まる
    try:
        store = BetStore(cfg.path("bet_done_path"))
    except BetDoneCorrupt as e:
        print(f"★ {e}")
        print("空で続けると二重投票になります。中身を直すか、退避してから動かしてください。")
        return 3

    if args.mode == "check":
        try:
            return Runner(cfg, store, args.mode, log).loop(once=args.once)
        except KeyboardInterrupt:
            log.event("終了", "Ctrl+C")
            return 0

    # dry / live は画面を触る。足りないものは動く前に言う
    if not cfg.telebote_url:
        print("config.json の telebote_url が空です。テレボートのURLを入れてください。")
        print("（新しい版なら最初から入っています。ZIP が古いかもしれません）")
        return 2
    missing = telebote_page.missing_selectors()
    if missing:
        print("telebote_page.py の SELECTORS がまだ空です: " + " / ".join(missing))
        print("  playwright codegen --channel=chrome " + cfg.telebote_url)
        print("で実際に1点買ってみて、出てきたコードから写してください。")
        return 2

    print(f"Chrome を起動しています（数秒かかります）: {cfg.path('profile_dir')}")
    try:
        with browser.open_context(cfg) as (_ctx, page):
            print(f"{cfg.telebote_url} を開きます")
            telebote_page.open_top(page, cfg.telebote_url)   # ここを起点にする
            if not ensure_logged_in(cfg, page):
                print("ログインが確認できないので止めます。")
                log.event("終了", "ログインしていない")
                return 2
            telebote_page.open_home(page)   # ログイン後のトップを起点にする
            runner = Runner(cfg, store, args.mode, log,
                            bet_fn=make_bet_fn(cfg, page),
                            keepalive_fn=make_keepalive_fn(cfg, page, log))
            return runner.loop(once=args.once)
    except browser.BrowserUnavailable as e:
        print(e)
        return 2
    except KeyboardInterrupt:
        # 記録は成功のたびに書いてあるので、ここで壊れるものは無い
        log.event("終了", "Ctrl+C")
        return 0


if __name__ == "__main__":
    sys.exit(main())
