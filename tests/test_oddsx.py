"""3連単以外の賭式のオッズ（oddsx.py）と、直前情報の追加項目（beforeinfo.py）。
公式ページの見本（tests/fixtures/、2026-11-10 福岡12R・平和島1R）で確かめる。外には触らない"""
import gzip
import json
import os
import shutil
import sys
import tempfile
import unittest

from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import beforeinfo as BI    # noqa: E402
import oddsx as X          # noqa: E402


def page(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as f:
        return f.read()


def at(arr, keys, key):
    return arr[keys.index(key)]


class TestOdds(unittest.TestCase):
    def test_単勝と複勝(self):
        tf = X.parse_tf(page("oddstf_20261110_22_12.html"))
        self.assertEqual(tf["win"], [2.0, 5.5, 2.8, 6.7, 10.2, 13.9])
        self.assertEqual(tf["place"][:3], [[1.0, 1.0], [2.4, 5.3], [1.1, 2.2]])

    def test_2連単と2連複(self):
        t = X.parse_2tf(page("odds2tf_20261110_22_12.html"))
        self.assertEqual(len(t["2t"]), 30)
        self.assertEqual(at(t["2t"], X.PAIRS, (1, 2)), 5.4)
        self.assertEqual(at(t["2t"], X.PAIRS, (2, 1)), 25.4)
        self.assertEqual(at(t["2t"], X.PAIRS, (3, 2)), 21.8)
        self.assertEqual(at(t["2t"], X.PAIRS, (6, 1)), 36.8)
        self.assertEqual(at(t["2f"], X.PAIRS2, (1, 3)), 2.1)
        self.assertEqual(at(t["2f"], X.PAIRS2, (2, 3)), 21.3)
        self.assertTrue(all(v is not None for v in t["2t"] + t["2f"]))

    def test_3連複(self):
        t = X.parse_3f(page("odds3f_20261110_22_12.html"))
        self.assertEqual(len(t["3f"]), 20)
        self.assertEqual(at(t["3f"], X.TRIOS, (1, 2, 3)), 2.4)
        self.assertEqual(at(t["3f"], X.TRIOS, (1, 2, 5)), 12.4)
        self.assertTrue(all(v is not None for v in t["3f"]))

    def test_拡連複(self):
        t = X.parse_k(page("oddsk_20261110_22_12.html"))
        self.assertEqual(at(t["k"], X.PAIRS2, (1, 2)), [1.9, 2.4])
        self.assertEqual(at(t["k"], X.PAIRS2, (2, 4)), [5.1, 5.7])
        self.assertTrue(all(v is not None for v in t["k"]))


class TestBeforeExtra(unittest.TestCase):
    def info(self, name):
        old = BI._soup
        BI._soup = lambda url, **k: BeautifulSoup(page(name), "html.parser")
        try:
            return BI.fetch("20261110", 22, 12, tries=1)
        finally:
            BI._soup = old

    def test_チルト_調整重量_前走(self):
        i = self.info("beforeinfo_20261110_22_12.html")
        self.assertEqual(i["tilt"], {1: 0.0, 2: 0.0, 3: 0.5, 4: 0.0, 5: -0.5, 6: 1.5})
        self.assertEqual(i["adj_weight"][4], 1.5)
        self.assertEqual(i["prev"][1], {"r": 3, "course": 3, "st": ".25", "chaku": "2"})
        self.assertEqual(i["parts"][1], [])
        self.assertEqual(i["propeller"][1], "")
        # 前からある項目は変わらない
        self.assertEqual(i["tenji"][3], 6.74)
        self.assertEqual(i["exhibition_st"][6], ".02")

    def test_1Rは前走が無い(self):
        i = self.info("beforeinfo_20261110_4_1.html")
        self.assertEqual(i["prev"], {})
        self.assertEqual(i["tilt"][2], -0.5)


class TestSnapPack(unittest.TestCase):
    def test_同じ時刻の3連単とxの行を両方残す(self):
        import snap_pack as SP
        tmp = tempfile.mkdtemp()
        cwd = os.getcwd()
        try:
            os.chdir(tmp)
            os.makedirs("snap")
            row = {"t": "10:00:00", "jcd": 22, "rno": 12, "left": 5}
            with open("snap/20261110.jsonl", "w") as f:
                f.write(json.dumps({**row, "odds": [10.0] * 120}) + "\n")
                f.write(json.dumps({**row, "x": {"win": [2.0] * 6}}) + "\n")
            SP.pack("20261110")
            with open("snap/20261110.jsonl", "w") as f:      # 2回目（同じ行）
                f.write(json.dumps({**row, "x": {"win": [2.0] * 6}}) + "\n")
            SP.pack("20261110")
            rows = json.load(gzip.open("odds_snap/20261110.json.gz", "rt"))["rows"]
            self.assertEqual(len(rows), 2)
            self.assertEqual(sum("x" in r for r in rows), 1)
        finally:
            os.chdir(cwd)
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
