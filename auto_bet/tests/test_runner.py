#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本体の1周ぶんの流れ。画面操作は偽物を差し込んで、ロジックだけ回す"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_bet                      # noqa: E402
import betlog                        # noqa: E402
import config as config_mod          # noqa: E402
import telebote_page                 # noqa: E402
from bet_store import BetStore       # noqa: E402
from jst import JST                  # noqa: E402
from tests.test_parts import DATE, NOW, day, race   # noqa: E402


class FakeBetter:
    """偽のページ。呼ばれた回数と、押したかどうかだけ覚える"""

    def __init__(self, pressed=True, raise_on=None, error=RuntimeError):
        self.calls = []
        self.pressed = pressed
        self.raise_on = raise_on
        self.error = error

    def __call__(self, b, yen, live):
        self.calls.append((b.key, yen, live))
        if self.raise_on and self.raise_on in b.key:
            raise self.error("画面が想定と違います")
        return self.pressed and live


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.cfg_path = os.path.join(self.dir, "config.json")
        self.write_config()
        self.store = BetStore(os.path.join(self.dir, "bet_done.json"))

    def write_config(self, **over):
        d = {
            "i_have_read_the_terms": False,
            "bet_yen": 100, "max_yen_per_day": 2000, "max_points_per_race": 4,
            "buy_obi": True, "buy_ana": False,
            "close_min_minutes": 3, "close_max_minutes": 25,
            "history_url": "https://example.invalid/history.json",
            "poll_seconds": 10,
        }
        d.update(over)
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        self.cfg = config_mod.load(self.cfg_path)
        return self.cfg

    def runner(self, mode, days, bet_fn=None, now=NOW):
        log = betlog.Log(self.cfg.path("log_path"), mode, echo=False)
        return auto_bet.Runner(
            self.cfg, self.store, mode, log, bet_fn=bet_fn,
            fetch_fn=lambda url: ({"days": days}, ""),
            now_fn=lambda: now,
        )


class TestCycle(Base):
    def test_checkはブラウザも記録も触らない(self):
        r = self.runner("check", [day([race()])])
        self.assertEqual(r.cycle(), "ok")
        self.assertEqual(self.store.keys(), set())

    def test_dryは押さないし記録もしない(self):
        fake = FakeBetter()
        r = self.runner("dry", [day([race()])], bet_fn=fake)
        self.assertEqual(r.cycle(), "ok")
        self.assertEqual([c[2] for c in fake.calls], [False])   # live=False で呼ぶ
        self.assertEqual(self.store.keys(), set())

    def test_dryは同じ組を何周も繰り返さない(self):
        fake = FakeBetter()
        r = self.runner("dry", [day([race()])], bet_fn=fake)
        r.cycle()
        r.cycle()
        self.assertEqual(len(fake.calls), 1)

    def test_liveは押して即記録する(self):
        fake = FakeBetter()
        r = self.runner("live", [day([race()])], bet_fn=fake)
        self.assertEqual(r.cycle(), "ok")
        self.assertEqual([c[2] for c in fake.calls], [True])
        self.assertIn("20260918-24-9-2-1-4-帯", self.store.keys())
        # ディスクにも即書かれている（途中で落ちても残る）
        self.assertIn("20260918-24-9-2-1-4-帯",
                      BetStore(self.cfg.path("bet_done_path")).keys())

    def test_二周目は同じ組を買わない(self):
        fake = FakeBetter()
        r = self.runner("live", [day([race()])], bet_fn=fake)
        r.cycle()
        r.cycle()
        self.assertEqual(len(fake.calls), 1)

    def test_押せなかったら記録しない(self):
        fake = FakeBetter(pressed=False)
        r = self.runner("live", [day([race()])], bet_fn=fake)
        r.cycle()
        self.assertEqual(self.store.keys(), set())

    def test_例外が出たらその周で打ち切り次のレースへ進まない(self):
        d = day([race(rno=9, close="15:10"), race(jcd=17, place="宮島", rno=3,
                                                  close="15:00")])
        fake = FakeBetter(raise_on="-17-")          # 締切が近い宮島が先に来る
        r = self.runner("live", [d], bet_fn=fake)
        self.assertEqual(r.cycle(), "abort")
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(self.store.keys(), set())

    def test_history_jsonが取れなくてもその周は何もせず落ちない(self):
        log = betlog.Log(self.cfg.path("log_path"), "live", echo=False)
        r = auto_bet.Runner(self.cfg, self.store, "live", log,
                            bet_fn=FakeBetter(),
                            fetch_fn=lambda url: (None, "取得できず: ネット断"),
                            now_fn=lambda: NOW)
        self.assertEqual(r.cycle(), "ok")

    def test_今日の日付がdaysに無くても落ちない(self):
        fake = FakeBetter()
        r = self.runner("live", [day([race()], date="20260917")], bet_fn=fake)
        self.assertEqual(r.cycle(), "ok")
        self.assertEqual(fake.calls, [])

    def test_STOPファイルがあれば止まる(self):
        open(self.cfg.path("stop_file"), "w").close()
        fake = FakeBetter()
        r = self.runner("live", [day([race()])], bet_fn=fake)
        self.assertEqual(r.cycle(), "stop")
        self.assertEqual(fake.calls, [])

    def test_1日の上限に達していたら買わない(self):
        self.write_config(max_yen_per_day=200)
        self.store.path = os.path.join(self.dir, "bet_done.json")
        fake = FakeBetter()
        r = self.runner("live", [day([race(combos=("2-1-4", "2-1-3", "2-4-1"))])],
                        bet_fn=fake)
        r.cycle()
        self.assertEqual(len(fake.calls), 2)              # 200円ぶんで打ち止め
        self.assertEqual(self.store.spent_on(DATE), 200)
        r.cycle()
        self.assertEqual(len(fake.calls), 2)              # 翌周も増えない

    def test_押した後で失敗したら投票済みとして記録し止まる(self):
        # 次の周で「まだ買っていない」と見なして買い直すのがいちばん危ない
        fake = FakeBetter(raise_on="-24-", error=telebote_page.BetUncertain)
        r = self.runner("live", [day([race()])], bet_fn=fake)
        self.assertEqual(r.cycle(), "halt")
        self.assertIn("20260918-24-9-2-1-4-帯", self.store.keys())
        self.assertIn("要確認", self.store.bets["20260918-24-9-2-1-4-帯"]["note"])
        r.cycle()
        self.assertEqual(len(fake.calls), 1)          # 次の周で買い直さない

    def test_haltのときは終了コード4で止まる(self):
        self.store = BetStore(os.path.join(self.dir, "another.json"))
        fake = FakeBetter(raise_on="-24-", error=telebote_page.BetUncertain)
        r = self.runner("live", [day([race()])], bet_fn=fake)
        self.assertEqual(r.loop(), 4)

    def test_記録できなければ押した後でも止まる(self):
        fake = FakeBetter()
        r = self.runner("live", [day([race()])], bet_fn=fake)
        def boom(*a, **k):
            raise OSError("書けません")
        r.store.record = boom
        self.assertEqual(r.cycle(), "halt")

    def test_押す直前に締切が近づいていたら見送る(self):
        # 選んだ時点では10分前。そのあと画面操作で手間取って2分前になった、の想定
        times = [NOW, datetime(2026, 9, 18, 14, 58, tzinfo=JST)]
        fake = FakeBetter()
        r = self.runner("live", [day([race(close="15:00")])], bet_fn=fake)
        r.now_fn = lambda: times.pop(0) if len(times) > 1 else times[0]
        r.cycle()
        self.assertEqual(fake.calls, [])
        self.assertEqual(self.store.keys(), set())

    def test_買い目が無い周でも動いていることが分かる行を出す(self):
        r = self.runner("check", [day([race(close="18:00")])])
        r.cycle()
        with open(self.cfg.path("log_path"), encoding="utf-8") as f:
            line = f.read().splitlines()[0]
        self.assertIn("見た", line)
        self.assertIn("今日 帯1 レース", line)
        self.assertIn("いま投票できる組 0件", line)
        self.assertIn("次は 大村9R 帯 締切18:00", line)

    def test_買い目が無い時間が続いたら画面を開き直す(self):
        # テレボートは一定時間操作がないとログアウトさせられる
        touched = []
        r = self.runner("live", [day([race(close="18:00")])], bet_fn=FakeBetter())
        r.keepalive_fn = lambda: touched.append(1) or True
        times = [NOW, NOW + timedelta(minutes=5), NOW + timedelta(minutes=20)]
        r.now_fn = lambda: times.pop(0) if len(times) > 1 else times[0]
        r.cycle()
        self.assertEqual(len(touched), 1)          # 初回
        r.cycle()
        self.assertEqual(len(touched), 1)          # 5分後はまだ
        r.cycle()
        self.assertEqual(len(touched), 2)          # 10分以上あいたら開き直す

    def test_ログインが切れていたら止まる(self):
        r = self.runner("live", [day([race(close="18:00")])], bet_fn=FakeBetter())
        r.keepalive_fn = lambda: False
        self.assertEqual(r.cycle(), "halt")
        self.assertIn("ログインが切れました", r.halt_reason)

    def test_開き直しに失敗しても落ちない(self):
        def boom():
            raise RuntimeError("画面が応答しません")
        r = self.runner("live", [day([race(close="18:00")])], bet_fn=FakeBetter())
        r.keepalive_fn = boom
        self.assertEqual(r.cycle(), "ok")

    def test_ログが1行1イベントで残る(self):
        r = self.runner("live", [day([race()])], bet_fn=FakeBetter())
        r.cycle()
        with open(self.cfg.path("log_path"), encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln]
        bets = [ln for ln in lines if "投票した" in ln]
        self.assertEqual(len(bets), 1)
        cols = bets[0].split("\t")
        self.assertEqual(cols[1:8], ["live", "大村9R", "帯", "2-1-4", "1点", "100円",
                                     "投票した"])

    def test_ループはonceで1周だけ回して戻る(self):
        fake = FakeBetter()
        r = self.runner("live", [day([race()])], bet_fn=fake)
        self.assertEqual(r.loop(once=True), 0)
        self.assertEqual(len(fake.calls), 1)


class TestMain(Base):
    def test_liveは確認フラグがfalseなら起動しない(self):
        code = auto_bet.main(["--mode", "live", "--config", self.cfg_path, "--once"])
        self.assertEqual(code, 2)

    def test_モードを指定しないと止まる(self):
        with self.assertRaises(SystemExit):
            auto_bet.main(["--config", self.cfg_path])

    def test_bet_doneが壊れていたら起動しない(self):
        with open(os.path.join(self.dir, "bet_done.json"), "w", encoding="utf-8") as f:
            f.write("{ こわれ")
        code = auto_bet.main(["--mode", "check", "--config", self.cfg_path, "--once"])
        self.assertEqual(code, 3)

    def test_設定が壊れていたら起動しない(self):
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write("{ こわれ")
        code = auto_bet.main(["--mode", "check", "--config", self.cfg_path, "--once"])
        self.assertEqual(code, 2)


class TestMidnight(Base):
    def test_深夜のレースも拾う(self):
        cfg = self.write_config()
        self.assertTrue(cfg.buy_obi)
        late = datetime(2026, 9, 18, 22, 55, tzinfo=JST)
        fake = FakeBetter()
        self.cfg.i_have_read_the_terms = True
        r = self.runner("live", [day([race(close="23:05")])], bet_fn=fake, now=late)
        r.cycle()
        self.assertEqual(len(fake.calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
