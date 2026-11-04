"""出走表が info.kyotei.fun から取れないとき、公式で代える（yosou.racecard）。外には触らない"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yosou as Y          # noqa: E402


def card(n_win=5.0):
    return [{"lane": i, "n_win": n_win, "cls_val": 2} for i in range(1, 7)]


class TestFallback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = (Y.CACHE_DIR, Y.RC.fetch_racecard, Y.OC.fetch_card, Y._KF_DOWN)
        Y.CACHE_DIR = self.tmp
        Y._KF_DOWN = False
        self.kf = []
        Y.RC.fetch_racecard = lambda d, j, r: self.kf.append(r) or None
        Y.OC.fetch_card = lambda d, j, r: card()

    def tearDown(self):
        Y.CACHE_DIR, Y.RC.fetch_racecard, Y.OC.fetch_card, Y._KF_DOWN = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_届かなければ公式で代えて覚えておく(self):
        rc = Y.racecard("20261104", 24, 5)
        self.assertEqual(len(rc), 6)
        self.assertEqual(rc[0]["src"], "official")
        Y.racecard("20261104", 24, 6)
        self.assertEqual(self.kf, [5])      # 2件目は info.kyotei.fun を待たない
        self.assertEqual(Y.racecard("20261104", 24, 5)[0]["src"], "official")   # cache

    def test_prefetchは公式で代えない(self):
        self.assertIsNone(Y.racecard("20261104", 24, 5, official=False))

    def test_取れればそのまま(self):
        Y.RC.fetch_racecard = lambda d, j, r: card(6.0)
        rc = Y.racecard("20261104", 24, 7)
        self.assertNotIn("src", rc[0])
        self.assertEqual(rc[0]["n_win"], 6.0)

    def test_公式も解析できなければ見送り(self):
        Y.OC.fetch_card = lambda d, j, r: card(None)
        self.assertIsNone(Y.racecard("20261104", 24, 8))


if __name__ == "__main__":
    unittest.main()
