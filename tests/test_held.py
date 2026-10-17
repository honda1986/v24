"""1着の差で帯を見送る足切り（select_rule.MAXR1、band_howto.md §27）の確認。外には触らない"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import select_rule as SR   # noqa: E402
import settle as S         # noqa: E402
import yosou as Y          # noqa: E402


class TestR1(unittest.TestCase):
    def test_市場と同じ見立てなら見送る(self):
        q1 = [.5, .2, .1, .1, .05, .05]
        ok, r1 = SR.r1_ok(q1, q1)
        self.assertFalse(ok)
        self.assertAlmostEqual(r1, 1.0)

    def test_どれか1艇が開いていれば買う(self):
        q1 = [.5, .2, .1, .1, .05, .05]
        p1 = [.45, .2, .1, .1, .1, .05]          # 5号艇が 2倍
        ok, r1 = SR.r1_ok(p1, q1)
        self.assertTrue(ok)
        self.assertAlmostEqual(r1, 2.0)

    def test_境目ちょうどは買う(self):
        ok, _ = SR.r1_ok([SR.MAXR1 * .2, .8], [.2, .8])
        self.assertTrue(ok)

    def test_settleと同じ値(self):
        self.assertEqual(S.MAXR1, SR.MAXR1)


class TestSiteRace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = Y.SITE
        Y.SITE = os.path.join(self.tmp, "history.json")

    def tearDown(self):
        Y.SITE = self.old

    def race(self):
        return json.load(open(Y.SITE, encoding="utf-8"))["days"][0]["races"][0]

    def put(self, status, held=None, r1=1.03, left=12):
        Y.site_race("20261018", "桐生", 1, 5, "10:30", status, 1, 2,
                    held=held, r1=r1, left=left)

    def test_最初の見送りを残す(self):
        self.put("買い目なし", ["1-2-3"], r1=1.03, left=12)
        self.put("買い目なし", ["1-3-2"], r1=1.04, left=9)
        r = self.race()
        self.assertEqual(r["held"], {"buys": ["1-2-3"], "left": 12, "r1": 1.03})
        self.assertEqual(r["r1"], 1.04)            # r1 は最新の回

    def test_あとで買っても見送りは消えない(self):
        self.put("買い目なし", ["1-2-3"])
        self.put("買い", None, r1=1.08, left=5)
        r = self.race()
        self.assertEqual(r["status"], "買い")
        self.assertEqual(r["held"]["buys"], ["1-2-3"])

    def test_穴のみのあとに見送りが来ても残す(self):
        self.put("穴のみ", None)
        self.put("買い目なし", ["2-1-3"])
        r = self.race()
        self.assertEqual(r["status"], "穴のみ")
        self.assertEqual(r["held"]["buys"], ["2-1-3"])

    def test_見送りが無ければ書かない(self):
        self.put("買い目なし", None)
        self.assertNotIn("held", self.race())


class TestSettleHeld(unittest.TestCase):
    def test_見送りにも結果を入れて別勘定で数える(self):
        tmp = tempfile.mkdtemp()
        site = os.path.join(tmp, "history.json")
        h = {"days": [{"date": "20261018", "picks": [], "races": [
            {"jcd": 1, "rno": 5, "status": "買い目なし",
             "held": {"buys": ["1-2-3", "1-3-2"], "left": 12, "r1": 1.03}},
            {"jcd": 1, "rno": 6, "status": "買い目なし",
             "held": {"buys": ["2-1-3"], "left": 8, "r1": 1.01}},
            {"jcd": 1, "rno": 7, "status": "買い目なし"}]}]}
        json.dump(h, open(site, "w", encoding="utf-8"))
        old = (S.SITE, S.kmap, S.rawmap, sys.argv)
        S.SITE = site
        S.kmap = lambda kdir, date: {(1, 5): ("1-3-2", 850.0), (1, 6): ("1-2-3", 500.0)}
        S.rawmap = lambda rawdir, date: None
        sys.argv = ["settle.py"]
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                S.main()
        finally:
            S.SITE, S.kmap, S.rawmap, sys.argv = old
        rs = json.load(open(site, encoding="utf-8"))["days"][0]["races"]
        self.assertEqual(rs[0]["held"]["hit"], True)
        self.assertEqual(rs[0]["held"]["ret"], 850.0)
        self.assertEqual(rs[1]["held"]["hit"], False)
        self.assertNotIn("held", rs[2])
        out = buf.getvalue()
        self.assertIn("1着の差で見送った帯", out)
        self.assertIn("回収率 283.3%", out)       # 850 / 300円
        self.assertIn("まだ確定したレースがありません", out)   # 帯の成績には混ぜない


if __name__ == "__main__":
    unittest.main()
