"""予想の精度（calib.py）と根拠（features.explain）の確認。外には触らない"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calib as C          # noqa: E402
import features as F       # noqa: E402


def lanes(p, q):
    return [{"lane": i + 1, "p": p[i], "q": q[i]} for i in range(6)]


class TestSummarize(unittest.TestCase):
    def day(self):
        return {"date": "20261010", "races": [
            {"jcd": 24, "rno": 1, "lanes": lanes([.6, .1, .1, .1, .05, .05],
                                                 [.5, .2, .1, .1, .05, .05]),
             "top": [[f"1-2-{c}", .1, 5.0, 1.0] for c in (3, 4, 5, 6)]
                    + [[f"1-3-{c}", .05, 9.0, 1.0] for c in (2, 4, 5, 6)]},
            {"jcd": 24, "rno": 2, "lanes": lanes([.3, .25, .15, .1, .1, .1],
                                                 [.35, .2, .15, .1, .1, .1])},
            {"jcd": 24, "rno": 3, "status": "波・風"},            # 内訳なし
        ], "picks": [{"jcd": 24, "rno": 2,                      # top は picks から借りる
                      "top": [["2-1-3", .2, 4.0, 1.2]] + [["9-9-9", .01, 99, 1]] * 7}]}

    def test_数える(self):
        res = {(24, 1): ("1-2-3", 500.0), (24, 2): ("2-1-3", 800.0)}
        st = C.summarize(self.day(), res)
        self.assertEqual(st["n"], 2)
        # 本命: 1R は1号艇(.6)が勝ち、2R は1号艇(.3)が負け
        self.assertEqual(st["p"]["fav"][0][:2], [2, 1])
        self.assertAlmostEqual(st["p"]["fav"][0][2], 0.9, places=6)
        self.assertEqual(st["p"]["fav"][1][:2], [1, 0])      # 混戦(.3)
        self.assertEqual(st["p"]["fav"][3][:2], [1, 1])      # 堅い(.6)
        # 全艇ぶん帯に入る
        self.assertEqual(sum(b[0] for b in st["p"]["cal"]), 12)
        self.assertEqual(sum(b[1] for b in st["q"]["cal"]), 2)
        # 3連単: 1R は上位8組に入り予想1位も的中、2R は picks の top で的中
        self.assertEqual(st["t8"][:2], [2, 2])
        self.assertEqual(st["t1"], [2, 2])
        ll = -(np.log(.6) + np.log(.25))
        self.assertAlmostEqual(st["p"]["ll"], round(ll, 4), places=4)

    def test_結果の無いレースは数えない(self):
        st = C.summarize(self.day(), {(24, 1): ("1-2-3", 500.0)})
        self.assertEqual(st["n"], 1)

    def test_picksだけの日は数えない(self):
        # races の内訳が消えた古い日。買ったレースだけで数えると偏る
        d = {"date": "20260901", "races": [{"jcd": 1, "rno": 1}],
             "picks": [{"jcd": 1, "rno": 1, "lanes": lanes([.5] + [.1] * 5, [.5] + [.1] * 5)}]}
        self.assertEqual(C.races_of(d), {})

    def test_少ない版で上書きしない(self):
        out = {"version": C.VERSION, "days": {"20261010": {"n": 99}}}
        C.S.kmap = lambda kdir, date: {(24, 1): ("1-2-3", 500.0)}
        n = C.update(out, [self.day()], "x", log=lambda *a: None)
        self.assertEqual(n, 0)
        self.assertEqual(out["days"]["20261010"]["n"], 99)


class TestExplain(unittest.TestCase):
    def test_市場と枠番は出さない(self):
        feats = ["lq", "lane", "tenji", "n_win", "mot_pure", "age"]
        c = np.array([[2.0, 1.0, 0.30, -0.10, 0.05, 0.9, 0.0],    # 最後は定数項
                      [0.0, 0.0, 0.001, 0.0, 0.0, 0.0, 0.0]])
        w = F.explain(c, feats)
        self.assertEqual(w[0], "tj+nw-mp+")      # 大きい順。lq/lane/age は入らない
        self.assertEqual(w[1], "")               # 小さすぎる寄与は出さない

    def test_群をまとめて足す(self):
        feats = ["tenji", "tenji_dev", "tenji_rk"]
        w = F.explain(np.array([[0.05, -0.02, -0.01, 0.0]]), feats)
        self.assertEqual(w, ["tj+"])


if __name__ == "__main__":
    unittest.main()
