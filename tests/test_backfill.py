"""過去の直前情報のさかのぼり（backfill_before.py）。外には触らない"""
import gzip
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import backfill_before as BB   # noqa: E402


def fake_info(date, jcd, rno, tries=1):
    six = {b: 6.7 for b in range(1, 7)}
    return {"tenji": six, "course_in": {b: b for b in range(1, 7)}, "exhibition_st": {1: ".10"},
            "weight": six, "weather": {"風速": 1.0}, "wind_w": 5, "venue_dir": 1,
            "tilt": {b: 0.0 for b in range(1, 7)}, "propeller": {}, "parts": {1: ["電気"]},
            "adj_weight": {1: 0.5}, "prev": {}}


class TestBackfill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        os.makedirs("raw")
        for d in ("20250101", "20250102", "20250103"):
            races = [{"jcd": 24, "rno": r} for r in (1, 2)] + [{"jcd": 1, "rno": 1}]   # 1 = 桐生（淡水）
            with gzip.open(f"raw/{d}.json.gz", "wt") as f:
                json.dump({"date": d, "races": races}, f)
        self.old = BB.BI.fetch
        BB.BI.fetch = fake_info

    def tearDown(self):
        BB.BI.fetch = self.old
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_(self, *a):
        sys.argv = ["backfill_before.py", "--raw", "raw", "--gap", "0", "--no-push", *a]
        BB.main()

    def test_日付を振り分けて淡水は取らない(self):
        self.run_("--shard", "1", "--shards", "2")
        self.assertEqual(sorted(os.listdir("before_hist")), ["20250102.json.gz"])
        d = json.load(gzip.open("before_hist/20250102.json.gz", "rt"))
        self.assertEqual([(r["jcd"], r["rno"]) for r in d["races"]], [(24, 1), (24, 2)])
        self.assertEqual(d["races"][0]["parts"], {"1": ["電気"]})
        self.assertEqual(d["races"][0]["tilt"]["6"], 0.0)

    def test_既にある日は取り直さない(self):
        self.run_()
        n = []
        BB.BI.fetch = lambda *a, **k: n.append(1) or fake_info(*a)
        self.run_()
        self.assertEqual(n, [])


if __name__ == "__main__":
    unittest.main()
