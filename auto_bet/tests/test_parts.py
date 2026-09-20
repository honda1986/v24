#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""サイトを触らずに確かめられるところを、全部ここで確かめる（部品編）"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as config_mod          # noqa: E402
import history_source                # noqa: E402
import selector                      # noqa: E402
import telebote_page                 # noqa: E402
from bet_store import BetDoneCorrupt, BetStore, make_key   # noqa: E402
from jst import JST                  # noqa: E402

DATE = "20260918"
NOW = datetime(2026, 9, 18, 14, 50, tzinfo=JST)


def cfg(**over):
    d = {
        "i_have_read_the_terms": False,
        "bet_yen": 100,
        "max_yen_per_day": 2000,
        "max_points_per_race": 4,
        "buy_obi": True,
        "buy_ana": False,
        "close_min_minutes": 3,
        "close_max_minutes": 25,
        "history_url": "https://example.invalid/history.json",
        "poll_seconds": 120,
    }
    d.update(over)
    return config_mod.from_dict(d)


def race(jcd=24, place="大村", rno=9, close="15:00", combos=("2-1-4",)):
    return {
        "jcd": jcd, "place": place, "rno": rno, "close": close,
        "buys": [{"combo": c, "odds": 12.9, "q": 0.058, "p": 0.072, "pq": 1.24}
                 for c in combos],
        "cost": 100 * len(combos),
        "combo": None, "pay": None, "hit": None, "ret": None,
    }


def day(picks=None, ana=None, date=DATE):
    d = {"date": date, "picks": picks if picks is not None else [], "races": [],
         "skipped": {}, "runs": 12, "last_run": "11:20"}
    if ana is not None:
        d["ana"] = ana
    return d


class TestSelect(unittest.TestCase):
    def test_締切10分前は選ばれる(self):
        res = selector.select(day([race(close="15:00")]), set(), 0, cfg(), NOW)
        self.assertEqual([b.combo for b in res.bets], ["2-1-4"])
        self.assertEqual(res.bets[0].place, "大村")
        self.assertEqual(res.bets[0].kind, "帯")

    def test_締切2分前は選ばれない(self):
        res = selector.select(day([race(close="14:52")]), set(), 0, cfg(), NOW)
        self.assertEqual(res.bets, [])

    def test_締切30分前は選ばれない(self):
        res = selector.select(day([race(close="15:20")]), set(), 0, cfg(), NOW)
        self.assertEqual(res.bets, [])

    def test_締切を大きく過ぎたレースは黙って飛ばす(self):
        res = selector.select(day([race(close="09:00")]), set(), 0, cfg(), NOW)
        self.assertEqual(res.bets, [])
        self.assertEqual(res.warnings, [])

    def test_すでにbet_doneにある組は選ばれない(self):
        done = {make_key(DATE, 24, 9, "2-1-4", "帯")}
        res = selector.select(day([race(combos=("2-1-4", "2-1-3"))]), done, 0, cfg(), NOW)
        self.assertEqual([b.combo for b in res.bets], ["2-1-3"])

    def test_1日の上限に達していたら何も選ばれない(self):
        res = selector.select(day([race()]), set(), 2000, cfg(max_yen_per_day=2000), NOW)
        self.assertEqual(res.bets, [])
        self.assertTrue(any("上限" in w for w in res.warnings))

    def test_上限の残りぶんだけ選ばれる(self):
        d = day([race(combos=("2-1-4", "2-1-3", "2-4-1"))])
        res = selector.select(d, set(), 1800, cfg(max_yen_per_day=2000), NOW)
        self.assertEqual(len(res.bets), 2)

    def test_上限nullは無制限(self):
        d = day([race(combos=("2-1-4", "2-1-3"))])
        res = selector.select(d, set(), 999999, cfg(max_yen_per_day=None), NOW)
        self.assertEqual(len(res.bets), 2)

    def test_点数が想定を超えたらレースごと見送って警告(self):
        d = day([race(combos=("1-2-3", "1-2-4", "1-3-2", "1-3-4", "1-4-2"))])
        res = selector.select(d, set(), 0, cfg(), NOW)
        self.assertEqual(res.bets, [])
        self.assertTrue(any("想定外" in w for w in res.warnings))

    def test_点数の上限nullなら何点でも買う(self):
        d = day([race(combos=("1-2-3", "1-2-4", "1-3-2", "1-3-4", "1-4-2"))])
        res = selector.select(d, set(), 0, cfg(max_points_per_race=None), NOW)
        self.assertEqual(len(res.bets), 5)

    def test_anaキーが無い日でも落ちない(self):
        res = selector.select(day([race()]), set(), 0, cfg(buy_ana=True), NOW)
        self.assertEqual(len(res.bets), 1)

    def test_穴側は既定で買わない(self):
        d = day([], ana=[race(rno=5, close="15:05")])
        self.assertEqual(selector.select(d, set(), 0, cfg(), NOW).bets, [])
        res = selector.select(d, set(), 0, cfg(buy_ana=True), NOW)
        self.assertEqual([b.kind for b in res.bets], ["穴"])

    def test_同じレースが帯と穴に出たら両方買う(self):
        r = race()
        d = day([r], ana=[dict(r, omin=8.0)])
        res = selector.select(d, set(), 0, cfg(buy_ana=True), NOW)
        self.assertEqual(sorted(b.kind for b in res.bets), ["帯", "穴"])
        self.assertEqual(len({b.key for b in res.bets}), 2)

    def test_今日の日付がdaysに無くても落ちない(self):
        self.assertEqual(selector.select(None, set(), 0, cfg(), NOW).bets, [])

    def test_締切が読めないレースは警告して見送る(self):
        res = selector.select(day([race(close="おかしい")]), set(), 0, cfg(), NOW)
        self.assertEqual(res.bets, [])
        self.assertEqual(len(res.warnings), 1)

    def test_締切が近い順に並ぶ(self):
        d = day([race(rno=9, close="15:10"), race(jcd=17, place="宮島", rno=3,
                                                  close="15:00")])
        res = selector.select(d, set(), 0, cfg(), NOW)
        self.assertEqual([b.rno for b in res.bets], [3, 9])

    def test_placeが欠けても場コードから補う(self):
        r = race()
        del r["place"]
        res = selector.select(day([r]), set(), 0, cfg(), NOW)
        self.assertEqual(res.bets[0].place, "大村")

    def test_キーの形が仕様どおり(self):
        res = selector.select(day([race()]), set(), 0, cfg(), NOW)
        self.assertEqual(res.bets[0].key, "20260918-24-9-2-1-4-帯")


class TestSummary(unittest.TestCase):
    def test_次に締め切られるレースを教える(self):
        d = day([race(close="15:00"), race(jcd=17, place="宮島", rno=3, close="16:30")])
        n_obi, n_ana, nxt = selector.summary(d, cfg(), NOW)
        self.assertEqual((n_obi, n_ana), (2, 0))
        self.assertIn("大村9R", nxt)
        self.assertIn("あと10分", nxt)

    def test_締切を過ぎたものは次に数えない(self):
        d = day([race(close="09:00"), race(jcd=17, place="宮島", rno=3, close="16:30")])
        self.assertIn("宮島3R", selector.summary(d, cfg(), NOW)[2])

    def test_この後の予定が無い日(self):
        self.assertIn("予定は無し", selector.summary(day([race(close="09:00")]),
                                                     cfg(), NOW)[2])

    def test_今日が無い日でも落ちない(self):
        self.assertEqual(selector.summary(None, cfg(), NOW)[:2], (0, 0))

    def test_穴側を買わない設定なら穴は数えない(self):
        d = day([race()], ana=[race(rno=5, close="15:05")])
        self.assertEqual(selector.summary(d, cfg(), NOW)[:2], (1, 0))
        self.assertEqual(selector.summary(d, cfg(buy_ana=True), NOW)[:2], (1, 1))


class TestHistorySource(unittest.TestCase):
    def test_キャッシュ避けのクエリが付く(self):
        self.assertEqual(history_source.bust("http://x/h.json", t=123),
                         "http://x/h.json?t=123")
        self.assertEqual(history_source.bust("http://x/h.json?a=1", t=123),
                         "http://x/h.json?a=1&t=123")

    def test_ネット断でも落ちない(self):
        def boom(req, timeout=None):
            raise OSError("ネットワークに届きません")
        data, why = history_source.fetch("http://x/h.json", opener=boom)
        self.assertIsNone(data)
        self.assertIn("取得できず", why)

    def test_中身が壊れていても落ちない(self):
        class Res:
            def read(self): return "{ こわれ".encode("utf-8")
            def __enter__(self): return self
            def __exit__(self, *a): return False
        data, why = history_source.fetch("http://x/h.json", opener=lambda *a, **k: Res())
        self.assertIsNone(data)
        self.assertIn("読めず", why)

    def test_daysが無ければ形が違うとして扱う(self):
        class Res:
            def read(self): return b'{"updated": "x"}'
            def __enter__(self): return self
            def __exit__(self, *a): return False
        data, why = history_source.fetch("http://x/h.json", opener=lambda *a, **k: Res())
        self.assertIsNone(data)
        self.assertIn("形が違う", why)

    def test_今日のぶんだけ取り出す(self):
        h = {"days": [day(date="20260917"), day([race()], date=DATE)]}
        self.assertEqual(history_source.pick_day(h, DATE)["date"], DATE)
        self.assertIsNone(history_source.pick_day(h, "20260919"))
        self.assertIsNone(history_source.pick_day({}, DATE))


class TestLocalHistory(unittest.TestCase):
    """同じ PC の history.json を直接読む（v24 を PC へ移したとき）"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "history.json")

    def put(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_URLかどうかを見分ける(self):
        self.assertTrue(history_source.is_url("https://example.invalid/h.json"))
        self.assertFalse(history_source.is_url(r"C:\boat\v24\history.json"))
        self.assertFalse(history_source.is_url("history.json"))
        self.assertFalse(history_source.is_url("/home/boat/history.json"))

    def test_読める(self):
        json.dump({"days": [day([race()])]}, open(self.path, "w", encoding="utf-8"),
                  ensure_ascii=False)
        data, why = history_source.fetch(self.path)
        self.assertEqual(why, "")
        self.assertEqual(history_source.pick_day(data, DATE)["date"], DATE)

    def test_書き込み中なら取れなかったことにする(self):
        self.put('{"days": [{"dat')
        data, why = history_source.fetch(self.path)
        self.assertIsNone(data)
        self.assertIn("書き込み中", why)

    def test_ファイルが無くても落ちない(self):
        data, why = history_source.fetch(os.path.join(self.dir, "まだ無い.json"))
        self.assertIsNone(data)
        self.assertIn("ありません", why)

    def test_日本語が化けない(self):
        d = day([race(place="びわこ")])
        json.dump({"days": [d]}, open(self.path, "w", encoding="utf-8"),
                  ensure_ascii=False)
        data, _ = history_source.fetch(self.path)
        self.assertEqual(data["days"][0]["picks"][0]["place"], "びわこ")


class TestBetStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "bet_done.json")

    def _bet(self, combo="2-1-4", kind="帯"):
        return selector.Bet(date=DATE, jcd=24, place="大村", rno=9, kind=kind,
                            close="15:00", combo=combo, yen=100, points=1,
                            minutes=10.0, key=make_key(DATE, 24, 9, combo, kind))

    def test_無いファイルは空で始まる(self):
        self.assertEqual(BetStore(self.path).keys(), set())

    def test_投票のたびに即書かれる(self):
        s = BetStore(self.path)
        s.record(self._bet(), "live")
        self.assertTrue(os.path.exists(self.path))
        self.assertIn("20260918-24-9-2-1-4-帯", BetStore(self.path).keys())

    def test_当日分だけ合計する(self):
        s = BetStore(self.path)
        s.record(self._bet(), "live")
        s.record(self._bet(combo="2-1-3"), "live")
        s.bets["古いの"] = {"date": "20260917", "yen": 5000}
        self.assertEqual(s.spent_on(DATE), 200)

    def test_同じキーを二度は書けない(self):
        s = BetStore(self.path)
        s.record(self._bet(), "live")
        with self.assertRaises(RuntimeError):
            s.record(self._bet(), "live")

    def test_帯と穴は別勘定(self):
        s = BetStore(self.path)
        s.record(self._bet(kind="帯"), "live")
        s.record(self._bet(kind="穴"), "live")
        self.assertEqual(len(s.keys()), 2)

    def test_壊れていたら空で続行せず止まる(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ こわれ")
        with self.assertRaises(BetDoneCorrupt):
            BetStore(self.path)

    def test_形が違っても止まる(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"bets": [1, 2]}, f)
        with self.assertRaises(BetDoneCorrupt):
            BetStore(self.path)


class TestConfig(unittest.TestCase):
    def test_上限はnullで無制限(self):
        c = cfg(max_yen_per_day=None, max_points_per_race=None)
        self.assertIsNone(c.max_yen_per_day)
        self.assertIsNone(c.max_points_per_race)

    def test_締切の範囲が逆なら止まる(self):
        with self.assertRaises(config_mod.ConfigError):
            cfg(close_min_minutes=30, close_max_minutes=25)

    def test_どちらも買わない設定は止まる(self):
        with self.assertRaises(config_mod.ConfigError):
            cfg(buy_obi=False, buy_ana=False)

    def test_覚書のキーは読み飛ばす(self):
        c = config_mod.from_dict({"_1_必ず読むこと": ["…"], "buy_obi": True})
        self.assertEqual(c.unknown_keys, [])

    def test_1点の金額は100円単位(self):
        with self.assertRaises(config_mod.ConfigError):
            cfg(bet_yen=150)

    def test_1日の上限が1点ぶんに満たなければ止まる(self):
        with self.assertRaises(config_mod.ConfigError):
            cfg(bet_yen=100, max_yen_per_day=50)


class TestConfirmArea(unittest.TestCase):
    """確認画面のどこを読むか。表が複数あるので選び間違えないこと"""

    REAL = ("No 場・レース・勝式 1 宮島7R 3連単 1 - 2 - 3 75.8 100円 "
            "合計ベット数 1ベット 合計金額 100円")

    class FakePage:
        def __init__(self, tables, body):
            self.tables, self.body = tables, body

        def locator(self, sel):
            outer = self

            class Loc:
                def count(self):
                    return len(outer.tables)

                def nth(self, i):
                    t = outer.tables[i]
                    return type("E", (), {"inner_text": lambda s=None, t=t: t})()
            return Loc()

        def inner_text(self, sel):
            return self.body

    def read(self, tables, body):
        page = self.FakePage(tables, body)
        return telebote_page.TelebotePage(page).confirm_text()

    def test_買い目の表が2つ目でも選べる(self):
        got = self.read(["入金 照会 マイページ", self.REAL], "全体 " + self.REAL)
        self.assertIn("宮島7R", got)

    def test_表に無ければ画面全体を読む(self):
        got = self.read(["関係ない表"], "全体 " + self.REAL)
        self.assertIn("宮島7R", got)

    def test_選んだ文字で照合が通る(self):
        got = self.read(["ヘッダー", self.REAL], "")
        self.assertEqual(
            telebote_page.verify_text(got, "宮島", 7, "1-2-3", 100, units=1), [])


class TestIsRace(unittest.TestCase):
    """URL を見て、目当てのレースに着いたかどうか"""

    class FakePage:
        def __init__(self, url):
            self.url = url

    def is_race(self, url, jcd=17, rno=3):
        page = telebote_page.TelebotePage(self.FakePage(url))
        b = selector.Bet(date=DATE, jcd=jcd, place="宮島", rno=rno, kind="帯",
                         close="15:00", combo="1-2-3", yen=100, points=1,
                         minutes=10.0, key="k")
        return page._is_race(b)

    def test_合っていれば真(self):
        self.assertTrue(self.is_race("https://bu.tbbr.jp/bet?hatsubaiKbn=0&jyoCode=17&raceNo=03"))

    def test_レース番号が違えば偽(self):
        self.assertFalse(self.is_race("https://bu.tbbr.jp/bet?hatsubaiKbn=0&jyoCode=17&raceNo=04"))

    def test_場が違えば偽(self):
        self.assertFalse(self.is_race("https://bu.tbbr.jp/bet?hatsubaiKbn=0&jyoCode=14&raceNo=03"))

    def test_トップへ戻されたら偽(self):
        self.assertFalse(self.is_race("https://bu.tbbr.jp/top?hatsubaiKbn=0"))

    def test_0詰めでなくても読める(self):
        self.assertTrue(self.is_race("https://bu.tbbr.jp/bet?jyoCode=17&raceNo=3"))


class TestConfirmVerify(unittest.TestCase):
    """確認画面の照合。ここが最後の砦

    文面は実際の確認画面（bu.tbbr.jp/betconf）に合わせてある。
    """

    def screen(self, place="鳴門", rno=9, kind="3連単", combo="2-3-5", yen=100, n=1):
        return (
            "投票はまだ完了していません。\n"
            "合計金額を入力し、「投票」を押して下さい。\n"
            "No 場・レース・勝式 オッズ 購入金額\n組番\n"
            f"1 {place}{rno}R {kind}\n{combo.replace('-', ' - ')}\n75.8\n{yen}円\n"
            f"合計ベット数 {n}ベット\n合計金額 {yen * n}円\n"
        )

    def ng(self, **over):
        return telebote_page.verify_text(self.screen(**over), "鳴門", 9, "2-3-5", 100,
                                         units=1)

    def test_一致すればNG無し(self):
        self.assertEqual(self.ng(), [])

    def test_組が違えば気づく(self):
        self.assertTrue(any("組" in x for x in self.ng(combo="2-3-4")))

    def test_レースが違えば気づく(self):
        self.assertTrue(any("レース番号" in x for x in self.ng(rno=8)))

    def test_場が違えば気づく(self):
        self.assertTrue(any("場" in x for x in self.ng(place="宮島")))

    def test_金額が違えば気づく(self):
        self.assertTrue(any("金額" in x for x in self.ng(yen=500)))

    def test_勝式が違えば気づく(self):
        self.assertTrue(any("勝式" in x for x in self.ng(kind="3連複")))

    def test_ベットリストに買い残りがあれば気づく(self):
        # 前の周で追加したまま投票しなかった組が残っていると、合計が合わない
        ng = self.ng(n=2)
        self.assertTrue(any("1ベット" in x for x in ng))
        self.assertTrue(any("合計金額" in x for x in ng))

    def test_全角や記号が違っても読み替える(self):
        text = "大村　９Ｒ　３連単　２＝１＝４　１００円"
        self.assertEqual(
            telebote_page.verify_text(text, "大村", 9, "2-1-4", 100, totals=False), [])

    def test_金額が口数でしか出ない画面でも読める(self):
        text = "鳴門 9R 3連単 1-2-4 1口"
        self.assertEqual(
            telebote_page.verify_text(text, "鳴門", 9, "1-2-4", 100, units=1,
                                      totals=False), [])

    def test_口数が違えば気づく(self):
        text = "鳴門 9R 3連単 1-2-4 5口"
        ng = telebote_page.verify_text(text, "鳴門", 9, "1-2-4", 100, units=1,
                                       totals=False)
        self.assertTrue(any("金額" in x for x in ng))

    def test_1点は1口(self):
        self.assertEqual(telebote_page.units_of(100), 1)

    def test_必要なセレクタは埋まっている(self):
        self.assertEqual(telebote_page.missing_selectors(), [])

    def test_セレクタが空なら理由を出して止まる(self):
        with self.assertRaises(telebote_page.SelectorNotSet):
            telebote_page._sel("まだ無いもの")


if __name__ == "__main__":
    unittest.main(verbosity=2)
