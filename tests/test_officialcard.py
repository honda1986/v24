"""公式の出走表の解析（officialcard.parse）。見本の HTML だけを使い、外には触らない"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import officialcard as OC  # noqa: E402


def load(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as f:
        return f.read()


class TestParse(unittest.TestCase):
    """2026/10/17 下関(19) 9R。6号艇は平均STが「-」の新人（v22 raw と突き合わせた値）"""

    @classmethod
    def setUpClass(cls):
        cls.rc = OC.parse(load("racelist_20261017_19_9.html"))

    def test_6艇とれる(self):
        self.assertEqual([x["lane"] for x in self.rc], [1, 2, 3, 4, 5, 6])

    def test_ふつうの艇(self):
        x = self.rc[0]
        self.assertEqual((x["toban"], x["cls_val"], x["age"], x["weight"]), (4531, 3, 37, 53.1))
        self.assertEqual((x["f_count"], x["l_count"], x["avg_st"]), (0, 0, 0.16))
        self.assertAlmostEqual(x["n_win"], 6.21)
        self.assertAlmostEqual(x["n_2ren"], 0.4803)
        self.assertAlmostEqual(x["l_win"], 5.53)
        self.assertAlmostEqual(x["l_2ren"], 0.3611)
        self.assertAlmostEqual(x["m_2ren"], 0.3495)
        self.assertAlmostEqual(x["b_2ren"], 0.3661)

    def test_平均STが無い新人でも列がずれない(self):
        x = self.rc[5]
        self.assertEqual((x["toban"], x["cls_val"], x["f_count"], x["l_count"]), (5450, 1, 1, 0))
        self.assertEqual(x["avg_st"], 0.0)            # v22 raw（info.kyotei.fun）と同じ
        self.assertAlmostEqual(x["n_win"], 1.98)      # ★直す前は 6.0（枠番）が入っていた
        self.assertAlmostEqual(x["n_2ren"], 0.0161)
        self.assertAlmostEqual(x["l_win"], 0.0)
        self.assertAlmostEqual(x["l_2ren"], 0.0)
        self.assertAlmostEqual(x["m_2ren"], 0.2609)
        self.assertAlmostEqual(x["b_2ren"], 0.3636)


class TestFirstDay(unittest.TestCase):
    """2026/10/17 児島(16) 1R。節の初日で今節成績の欄が空。直す前は全艇の勝率が None になっていた"""

    def test_初日でも勝率がとれる(self):
        rc = OC.parse(load("racelist_20261017_16_1.html"))
        got = [(x["n_win"], x["avg_st"]) for x in rc]
        self.assertEqual(got, [(6.7, 0.17), (5.24, 0.18), (4.96, 0.2),
                               (5.84, 0.16), (3.23, 0.2), (4.42, 0.17)])
        x = rc[0]
        self.assertAlmostEqual(x["n_2ren"], 0.486)
        self.assertAlmostEqual(x["l_win"], 5.93)
        self.assertAlmostEqual(x["m_2ren"], 0.342)
        self.assertAlmostEqual(x["b_2ren"], 0.2952)


if __name__ == "__main__":
    unittest.main()
