"""PC と GitHub の引き継ぎ（runner.py の心拍 / standby.py / watchdog.py）。外には触らない"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import runner as R        # noqa: E402
import standby as SB      # noqa: E402
import watchdog as W      # noqa: E402

JST = R.JST


def at(hhmm, day=4):
    h, m = hhmm.split(":")
    return datetime(2026, 11, day, int(h), int(m), tzinfo=JST)


class Repo(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.repo, "state"))

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def alive(self, host, t, **kw):
        R.save_json(R.alive_path(self.repo, host), {"t": t.isoformat(), **kw})

    def history(self, last_run, date="20261104"):
        R.save_json(os.path.join(self.repo, "history.json"),
                    {"days": [{"date": date, "last_run": last_run}]})


class TestHandover(Repo):
    def test_GitHubが回っていればPCは待つ(self):
        self.alive("gh", at("10:00"), active=True)
        self.assertTrue(R.gh_running(self.repo, at("10:05"))[0])

    def test_GitHubの心拍が古ければ待たない(self):
        # ジョブが途中で切られて active が残っても、8分で PC が戻れる
        self.alive("gh", at("10:00"), active=True)
        self.assertFalse(R.gh_running(self.repo, at("10:09"))[0])

    def test_GitHubが止まったと書いたら待たない(self):
        self.alive("gh", at("10:00"), active=False)
        self.assertFalse(R.gh_running(self.repo, at("10:01"))[0])

    def test_心拍は新しいほうを残す(self):
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "state"))
            # 手元には古い「相手の心拍」、リモートには新しいもの
            R.save_json(os.path.join(tmp, "state", "alive_gh.json"),
                        {"t": at("10:00").isoformat(), "active": True})
            R.save_json(os.path.join(tmp, "state", "alive_pc.json"),
                        {"t": at("10:06").isoformat()})
            self.alive("gh", at("10:05"), active=False)
            self.alive("pc", at("09:00"))
            R.integrate(tmp, self.repo, log=lambda *a: None)
            gh = R.read_alive(self.repo, "gh")
            self.assertEqual(gh["t"], at("10:05").isoformat())    # リモートの新しいほう
            self.assertFalse(gh["active"])
            self.assertEqual(R.read_alive(self.repo, "pc")["t"], at("10:06").isoformat())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_touch_aliveは足した項目を残す(self):
        R.touch_alive(self.repo, "pc", motor="20261104")
        a = R.touch_alive(self.repo, "pc")
        self.assertEqual(a["motor"], "20261104")
        self.assertIn("t", a)


class TestStandbyJudge(Repo):
    def test_PCが動いていれば引き継がない(self):
        self.alive("pc", at("10:50"))
        go, why = SB.judge(self.repo, at("11:00"))
        self.assertFalse(go)
        self.assertIn("PC が動いています", why)

    def test_PCが15分より前なら引き継ぐ(self):
        self.alive("pc", at("10:44"))
        self.assertTrue(SB.judge(self.repo, at("11:00"))[0])
        self.alive("pc", at("10:45"))
        self.assertFalse(SB.judge(self.repo, at("11:00"))[0])

    def test_前の晩から止まっていれば引き継ぐ(self):
        self.alive("pc", at("21:39", day=3))
        go, why = SB.judge(self.repo, at("11:08"))
        self.assertTrue(go)
        self.assertIn("止まっています", why)

    def test_朝はPCが寝ているのが普通なので見ない(self):
        self.alive("pc", at("23:57", day=3))
        self.assertFalse(SB.judge(self.repo, at("07:30"))[0])
        self.assertFalse(SB.judge(self.repo, at("08:09"))[0])
        self.assertTrue(SB.judge(self.repo, at("08:10"))[0])

    def test_入れた直後はhistoryのlast_runで見る(self):
        # alive_pc.json がまだ無い（PC が新しい runner.py で動く前）
        self.history("10:58")
        self.assertFalse(SB.judge(self.repo, at("11:00"))[0])
        self.history("10:30")
        self.assertTrue(SB.judge(self.repo, at("11:00"))[0])

    def test_GitHubが回ったあとはlast_runをPCの心拍とみなさない(self):
        self.history("10:58")                  # これは GitHub が書いたもの
        self.alive("gh", at("10:58"), active=True)
        self.assertTrue(SB.judge(self.repo, at("11:00"))[0])

    def test_手動のforceは時間も心拍も見ない(self):
        self.alive("pc", at("10:59"))
        self.assertTrue(SB.judge(self.repo, at("11:00"), force=True)[0])


class TestWatchdog(unittest.TestCase):
    def test_PCの心拍が古ければ鳴らす_予備運転中と書く(self):
        alert, why = W.judge({"days": [{"date": "20261104", "last_run": "10:58"}]},
                             at("11:00"), alive_pc={"t": at("10:00").isoformat()},
                             alive_gh={"t": at("10:58").isoformat(), "active": True})
        self.assertTrue(alert)              # last_run は新しいが、それは予備運転のもの
        self.assertIn("60分", why)
        self.assertIn("予備運転しています", why)

    def test_予備運転が回っていなければそう書く(self):
        alert, why = W.judge({}, at("11:00"), alive_pc={"t": at("10:00").isoformat()})
        self.assertTrue(alert)
        self.assertIn("まだ回っていません", why)

    def test_PCが動いていれば鳴らさない(self):
        alert, why = W.judge({}, at("11:00"), alive_pc={"t": at("10:57").isoformat()})
        self.assertFalse(alert)
        self.assertIn("正常", why)


if __name__ == "__main__":
    unittest.main()
