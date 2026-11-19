"""uchisankaku が空のとき、公式の出走表から今節成績を作る（officialsetsu / yosou.official_setsu）。外には触らない"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import officialsetsu as OS   # noqa: E402
import yosou as Y            # noqa: E402


def load(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as f:
        return f.read()


class TestParse(unittest.TestCase):
    """2026/10/17 下関 9R（2日目）。期待値は同じ日の uchisankaku（v22 tokuten）の値"""

    def test_2日目は前日までの走だけ数える(self):
        p = OS.parse(load("racelist_20261017_19_9.html"), "20261017")
        self.assertEqual((p["day_no"], p["n_days"], p["race"]["name"]), (2, 5, "予選"))
        L = p["race"]["lanes"]
        self.assertEqual([x["toban"] for x in L], [4531, 3976, 3797, 4563, 4910, 5450])
        self.assertEqual([x["cls"] for x in L], ["A2", "B1", "B1", "B1", "A1", "B2"])
        self.assertEqual([x["n_runs"] for x in L], [2, 2, 1, 1, 2, 1])
        self.assertEqual([x["st_setsu"] for x in L], [0.11, 0.18, 0.26, 0.14, 0.15, 0.31])
        # 得点率は近似。5号艇はドリーム戦を含むので uchisankaku（6.5）とずれる
        self.assertEqual([x["tokuten"] for x in L], [6.0, 7.0, 2.0, 1.0, 4.5, 2.0])
        self.assertTrue(all(x["rank"] is None and x["genten"] == 0.0 for x in L))

    def test_初日は走が無い(self):
        p = OS.parse(load("racelist_20261017_16_1.html"), "20261017")
        self.assertEqual(p["day_no"], 1)
        L = p["race"]["lanes"]
        self.assertEqual([x["n_runs"] for x in L], [0] * 6)
        self.assertTrue(all(x["st_setsu"] is None and x["tokuten"] is None for x in L))
        self.assertEqual(L[0]["toban"], 3541)


class TestFallback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = (Y.CACHE_DIR, Y.OS.fetch_page)
        Y.CACHE_DIR = self.tmp
        self.n = 0

        def fake(date, jcd, rno):
            self.n += 1
            p = OS.parse(load("racelist_20261017_19_9.html"), "20261017")
            p["race"]["rno"] = rno
            return {"date": date, "jcd": jcd, "sched": p["sched"], "day_no": p["day_no"],
                    "n_days": p["n_days"], "races": [p["race"]], "src": "official"}
        Y.OS.fetch_page = fake

    def tearDown(self):
        Y.CACHE_DIR, Y.OS.fetch_page = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_1レース1回だけ取って覚えておく(self):
        a = Y.official_setsu("20261017", 19, 9)
        b = Y.official_setsu("20261017", 19, 9)
        self.assertEqual(self.n, 1)
        self.assertEqual(a["day_no"], b["day_no"])

    def test_予想の入力が組める(self):
        pg = Y.official_setsu("20261017", 19, 9)
        rc = [{"lane": i, "cls_val": 2, "n_win": 5.0, "avg_st": 0.16} for i in range(1, 7)]
        lanes, meta = Y.build_lanes(rc, pg, 19, 9, {"4531": 0.01})
        self.assertEqual([x["toban"] for x in lanes], [4531, 3976, 3797, 4563, 4910, 5450])
        self.assertEqual(lanes[0]["mot_pure"], 0.01)
        self.assertEqual(lanes[1]["tok"], 7.0)
        self.assertEqual((meta["day_no"], meta["n_days"], meta["is_final"]), (2, 5, 0))


if __name__ == "__main__":
    unittest.main()
