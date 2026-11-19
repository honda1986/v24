"""PC で v23 も回す（v23pc.maybe_run）。git と v23 の本体は差し替えて、外には触らない"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import v23pc as V   # noqa: E402

STUB_YOSOU = """import json, os, sys
os.makedirs("yosou", exist_ok=True)
json.dump({"topic": os.environ.get("NTFY_TOPIC")}, open("yosou/data.json", "w"))
print("20261120 の予想を作ります")
"""


class TestMaybeRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.v24 = os.path.join(self.tmp, "v24")
        self.v23 = os.path.join(self.tmp, "v23")
        self.logs = os.path.join(self.tmp, "logs")
        os.makedirs(os.path.join(self.v23, ".git"))
        os.makedirs(self.v24)
        for name, body in (("yosou.py", STUB_YOSOU), ("motor.py", "print('motor')\n")):
            with open(os.path.join(self.v23, name), "w") as f:
                f.write(body)
        self.calls, self.lines = [], []
        self.env = {k: os.environ.get(k) for k in ("NTFY_TOPIC", "NTFY_TOPIC_V23")}
        os.environ["NTFY_TOPIC"] = "v24topic"
        os.environ.pop("NTFY_TOPIC_V23", None)

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, repo, *args, timeout=None):
        self.calls.append(args)
        if args[:2] == ("diff", "--cached"):
            return False, ""          # 変更あり
        if args[:2] == ("config", "--get"):
            return False, ""          # 名前がまだ無い
        return True, ""

    def run_once(self, started=None):
        return V.maybe_run(self.v24, os.path.join(self.tmp, "v22"), sys.executable, self.lines.append,
                           self.logs, started or time.time(), self.git)

    def test_回して心拍を足して_push(self):
        self.assertEqual(self.run_once(), "push")
        with open(os.path.join(self.v23, "yosou", "data.json")) as f:
            self.assertEqual(json.load(f)["topic"], "v24topic")      # NTFY_TOPIC_V23 が無ければ v24 と同じ
        self.assertTrue(os.path.exists(os.path.join(self.v23, "yosou", "pc_alive.json")))
        self.assertIn(("push", "-q", "origin", "HEAD:main"), self.calls)
        self.assertIn(("reset", "-q", "--hard", "origin/main"), self.calls)
        self.assertIn(("config", "user.name", "boat-pc"), self.calls)     # commit する名前を入れる
        with open(os.path.join(self.v24, "state", "v23_pc.json")) as f:
            self.assertEqual(json.load(f)["result"], "push")      # 結果は v24 の state に残る

    def test_commit_できなければそこで止める(self):
        def git(repo, *args, timeout=None):
            self.calls.append(args)
            if args[:2] == ("diff", "--cached"):
                return False, ""
            if args[0] == "commit":
                return False, "Author identity unknown"
            return True, ""
        r = V.maybe_run(self.v24, os.path.join(self.tmp, "v22"), sys.executable, self.lines.append,
                        self.logs, time.time(), git)
        self.assertEqual(r, "commit できず")
        self.assertFalse(any(c[0] == "push" for c in self.calls))

    def test_push_できなければ理由を_state_に残す(self):
        def git(repo, *args, timeout=None):
            if args[:2] == ("diff", "--cached"):
                return False, ""
            if args[0] == "push":
                return False, "remote: Permission to honda1986/boatrace-appV23.git denied"
            return True, ""
        V.time.sleep, old = (lambda s: None), V.time.sleep
        try:
            r = V.maybe_run(self.v24, os.path.join(self.tmp, "v22"), sys.executable, self.lines.append,
                            self.logs, time.time(), git)
        finally:
            V.time.sleep = old
        self.assertEqual(r, "push できず")
        with open(os.path.join(self.v24, "state", "v23_pc.json")) as f:
            st = json.load(f)
        self.assertTrue(any("denied" in b for b in st["bad"]))

    def test_15分たつまでは回さない(self):
        self.run_once()
        self.calls.clear()
        self.assertEqual(self.run_once(), "まだ")
        self.assertEqual(self.calls, [])

    def test_時間が残っていなければ次の回へ(self):
        self.assertEqual(self.run_once(started=time.time() - 400), "時間なし")
        self.assertEqual(self.calls, [])

    def test_v23専用の宛先があればそちら(self):
        os.environ["NTFY_TOPIC_V23"] = "v23topic"
        self.run_once()
        with open(os.path.join(self.v23, "yosou", "data.json")) as f:
            self.assertEqual(json.load(f)["topic"], "v23topic")

    def test_無ければ_clone(self):
        shutil.rmtree(os.path.join(self.v23, ".git"))
        self.run_once()
        self.assertEqual(self.calls[0][0], "clone")


if __name__ == "__main__":
    unittest.main()
