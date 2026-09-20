#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watchdog.py の判定（仕様 §8 の最後）"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import watchdog    # noqa: E402
from watchdog import JST    # noqa: E402

TODAY = "20260920"


def at(hhmm):
    h, m = hhmm.split(":")
    return datetime(2026, 9, 20, int(h), int(m), tzinfo=JST)


def history(last_run="09:55", date=TODAY):
    day = {"date": date, "picks": [], "runs": 3}
    if last_run is not None:
        day["last_run"] = last_run
    return {"days": [day]}


class TestJudge(unittest.TestCase):
    def test_10時で最後が0955なら何もしない(self):
        alert, why = watchdog.judge(history("09:55"), at("10:00"))
        self.assertFalse(alert)
        self.assertIn("正常", why)

    def test_10時で最後が0920なら警告(self):
        alert, why = watchdog.judge(history("09:20"), at("10:00"))
        self.assertTrue(alert)
        self.assertIn("40分", why)
        self.assertIn("手動実行", why)

    def test_今日の要素が無ければ警告(self):
        alert, why = watchdog.judge(history(date="20260919"), at("10:00"))
        self.assertTrue(alert)
        self.assertIn("一度も動いていません", why)

    def test_0730は時間外(self):
        alert, why = watchdog.judge(history("09:55"), at("07:30"))
        self.assertFalse(alert)
        self.assertIn("時間外", why)

    def test_2330も時間外(self):
        self.assertFalse(watchdog.judge(history("23:05"), at("23:30"))[0])

    def test_境目(self):
        self.assertFalse(watchdog.judge(history("08:35"), at("08:39"))[0])  # 手前
        self.assertTrue(watchdog.judge(history("07:00"), at("08:40"))[0])   # ここから

    def test_ちょうど30分はまだ許す(self):
        self.assertFalse(watchdog.judge(history("09:30"), at("10:00"))[0])
        self.assertTrue(watchdog.judge(history("09:29"), at("10:00"))[0])

    def test_last_runが無ければ警告(self):
        alert, why = watchdog.judge(history(None), at("10:00"))
        self.assertTrue(alert)
        self.assertIn("記録されていません", why)

    def test_last_runが壊れていても落ちない(self):
        h = history("—")
        self.assertTrue(watchdog.judge(h, at("10:00"))[0])

    def test_daysが空でも落ちない(self):
        self.assertTrue(watchdog.judge({"days": []}, at("10:00"))[0])
        self.assertTrue(watchdog.judge({}, at("10:00"))[0])

    def test_pushできていない可能性にも触れる(self):
        self.assertIn("push", watchdog.judge(history("09:00"), at("10:00"))[1])


class TestMain(unittest.TestCase):
    def test_history_jsonが無くても落ちない(self):
        self.assertEqual(watchdog.main(["--history", "どこにもない.json"]), 0)

    def test_実物のhistory_jsonを読める(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, "history.json")
        if not os.path.exists(path):
            self.skipTest("history.json が無い")
        self.assertEqual(watchdog.main(["--history", path, "--now", "07:00"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
