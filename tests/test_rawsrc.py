"""v22 の raw / tokuten が空の日の代わり（rawsrc.py / collect_raw.py）。外には触らない"""
import gzip
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import collect_raw as CR   # noqa: E402
import rawsrc as RS        # noqa: E402


def put(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt") as f:
        json.dump(obj, f)


class TestRawsrc(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.v22, self.r24 = f"{self.t}/raw", f"{self.t}/raw24"
        put(f"{self.v22}/20261019.json.gz", {"races": [{"jcd": 1, "src": "v22"}]})
        put(f"{self.v22}/20261020.json.gz", {"races": []})                 # v22 が空の日
        put(f"{self.r24}/20261020.json.gz", {"races": [{"jcd": 2, "src": "official"}]})
        put(f"{self.r24}/20261019.json.gz", {"races": [{"jcd": 3, "src": "official"}]})   # 突き合わせ用

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def test_v22にあればv22_空ならraw24(self):
        self.assertEqual(RS.load_raw(self.v22, "20261019", self.r24)["races"][0]["src"], "v22")
        self.assertEqual(RS.load_raw(self.v22, "20261020", self.r24)["races"][0]["src"], "official")
        self.assertEqual(RS.load_raw(self.v22, "20261021", self.r24)["races"], [])
        self.assertEqual(RS.raw_days(self.v22, self.r24), ["20261019", "20261020"])

    def test_tokutenはv22を優先(self):
        put(f"{self.t}/tok/20261019.json.gz", {})
        put(f"{self.t}/tok24/20261019.json.gz", {})
        put(f"{self.t}/tok24/20261020.json.gz", {})
        f = RS.tokuten_files(f"{self.t}/tok", f"{self.t}/tok24")
        self.assertIn("/tok/", f["20261019"])
        self.assertIn("/tok24/", f["20261020"])


class TestBuild(unittest.TestCase):
    def test_公式の出走表とKファイルから1レース(self):
        k = {"jcd": 24, "rno": 5, "hit": "1-2-3", "pay_3t": 1230, "wind": 2, "wave": 1,
             "entries": [{"lane": i, "chaku": f"0{i}", "tenji": 6.7, "course": i, "toban": 4000 + i}
                         for i in range(1, 7)]}
        k["entries"][5]["chaku"] = "F"
        card = [{"lane": i, "cls_val": 2, "age": 30, "weight": 52.0, "f_count": 0, "avg_st": 0.16,
                 "n_win": 5.0, "n_2ren": 0.3, "l_win": 5.0, "l_2ren": 0.3, "m_2ren": 0.35,
                 "b_2ren": 0.3, "toban": 4000 + i} for i in range(1, 7)]
        r = CR.build_race("20261025", k, card, [10.0] * 120)
        self.assertEqual(r["hit"], "1-2-3")
        self.assertEqual(r["entries"][0]["rank"], 1)
        self.assertIsNone(r["entries"][5]["rank"])       # F は着順なし
        self.assertEqual(r["entries"][2]["course_in"], 3)
        self.assertEqual(r["entries"][0]["n_2ren"], 0.3)
        self.assertEqual(r["weather"]["wind"], 2)
        self.assertIsNone(CR.build_race("20261025", k, card[:5], [10.0] * 120))   # 出走表が欠け
        self.assertIsNone(CR.build_race("20261025", k, card, None))               # オッズが無い


if __name__ == "__main__":
    unittest.main()
