#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""runner.py の確かめ（GitHub にも競艇サイトにも触らない）

本物の git を使って、リモート役の空リポジトリと手元のクローンを作り、
仕様 §8 の項目をそのまま試す。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import runner    # noqa: E402

V24 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sh(cwd, *args):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {p.stderr}")
    return p.stdout


def write(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False)


def read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def day(date="20260920", picks=None, last_run="10:00", runs=1):
    return {"date": date, "picks": picks or [], "skipped": {},
            "runs": runs, "last_run": last_run}


def pick(jcd=24, rno=9, combo="2-1-4", hit=None):
    return {"jcd": jcd, "place": "大村", "rno": rno, "close": "15:00",
            "buys": [{"combo": combo}], "cost": 100, "hit": hit}


class Base(unittest.TestCase):
    """リモート役 + PC 役 + もう1台（GitHub の予備運転役）"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.remote = os.path.join(self.dir, "remote.git")
        sh(self.dir, "git", "init", "-q", "--bare", "-b", "main", self.remote)

        self.pc = self.clone("pc")
        self.other = self.clone("other")

    def clone(self, name):
        path = os.path.join(self.dir, name)
        sh(self.dir, "git", "clone", "-q", self.remote, path)
        sh(path, "git", "config", "user.name", name)
        sh(path, "git", "config", "user.email", f"{name}@test")
        # merge_history.py を使うので、本物を置いておく
        shutil.copy2(os.path.join(V24, "merge_history.py"), path)
        if not os.path.exists(os.path.join(path, "history.json")):
            write(os.path.join(path, "history.json"), {"days": []})
            os.makedirs(os.path.join(path, "state"), exist_ok=True)
            sh(path, "git", "add", "-A")
            sh(path, "git", "commit", "-q", "-m", "init")
            sh(path, "git", "push", "-q", "origin", "main")
        else:
            sh(path, "git", "pull", "-q", "origin", "main")
        return path

    def quiet(self, *a):
        pass


class TestIntegrate(Base):
    """取り込み（仕様 §8 の1つ目）"""

    def test_リモートにだけある通知済みは消えない(self):
        write(os.path.join(self.other, "state/notified_20260920.json"), ["24-9"])
        sh(self.other, "git", "add", "-A")
        sh(self.other, "git", "commit", "-q", "-m", "other")
        sh(self.other, "git", "push", "-q", "origin", "main")

        write(os.path.join(self.pc, "state/notified_20260920.json"), ["17-3"])
        runner.save(self.pc, "pc", self.quiet)

        got = read(os.path.join(self.pc, "state/notified_20260920.json"))
        self.assertEqual(sorted(got), ["17-3", "24-9"])

    def test_ローカルにだけある通知済みは消えない(self):
        write(os.path.join(self.pc, "state/notified_20260920.json"), ["17-3"])
        runner.save(self.pc, "pc", self.quiet)
        self.assertEqual(read(os.path.join(self.pc, "state/notified_20260920.json")),
                         ["17-3"])

    def test_settleが入れた結果は消えない(self):
        # リモート（motor が settle を流した後）に hit が入っている
        write(os.path.join(self.other, "history.json"),
              {"days": [day(picks=[pick(hit=1)])]})
        sh(self.other, "git", "add", "-A")
        sh(self.other, "git", "commit", "-q", "-m", "settle")
        sh(self.other, "git", "push", "-q", "origin", "main")

        # PC 側は同じレースを hit なしで持っている（yosou が書いた直後）
        write(os.path.join(self.pc, "history.json"),
              {"days": [day(picks=[pick(hit=None)], last_run="10:30")]})
        runner.save(self.pc, "pc", self.quiet)

        got = read(os.path.join(self.pc, "history.json"))["days"][0]
        self.assertEqual(got["picks"][0]["hit"], 1)        # 消えていない
        self.assertEqual(got["last_run"], "10:30")         # 新しいほうが残る

    def test_両方の日が残る(self):
        write(os.path.join(self.other, "history.json"),
              {"days": [day(date="20260919", picks=[pick(rno=1)])]})
        sh(self.other, "git", "add", "-A")
        sh(self.other, "git", "commit", "-q", "-m", "old")
        sh(self.other, "git", "push", "-q", "origin", "main")

        write(os.path.join(self.pc, "history.json"),
              {"days": [day(date="20260920", picks=[pick(rno=9)])]})
        runner.save(self.pc, "pc", self.quiet)

        dates = [d["date"] for d in read(os.path.join(self.pc, "history.json"))["days"]]
        self.assertEqual(dates, ["20260919", "20260920"])

    def test_cacheはローカルを残す(self):
        write(os.path.join(self.pc, "cache/card_20260920_24.json"), {"a": 1})
        runner.save(self.pc, "pc", self.quiet)
        self.assertTrue(os.path.exists(
            os.path.join(self.pc, "cache/card_20260920_24.json")))


class TestPush(Base):
    def test_pushできなくても何も消えない(self):
        write(os.path.join(self.pc, "state/notified_20260920.json"), ["24-9"])
        write(os.path.join(self.pc, "history.json"), {"days": [day()]})
        sh(self.pc, "git", "remote", "set-url", "origin",
           os.path.join(self.dir, "どこにもない.git"))

        runner.save(self.pc, "pc", self.quiet)       # 例外を出さない

        self.assertEqual(read(os.path.join(self.pc, "state/notified_20260920.json")),
                         ["24-9"])
        self.assertEqual(read(os.path.join(self.pc, "history.json"))["days"][0]["date"],
                         "20260920")

    def test_次の実行でpushされる(self):
        write(os.path.join(self.pc, "state/notified_20260920.json"), ["24-9"])
        sh(self.pc, "git", "remote", "set-url", "origin",
           os.path.join(self.dir, "どこにもない.git"))
        runner.save(self.pc, "pc", self.quiet)

        sh(self.pc, "git", "remote", "set-url", "origin", self.remote)
        write(os.path.join(self.pc, "state/notified_20260920.json"), ["24-9", "17-3"])
        self.assertEqual(runner.save(self.pc, "pc2", self.quiet), "push")

        sh(self.other, "git", "pull", "-q", "origin", "main")
        got = read(os.path.join(self.other, "state/notified_20260920.json"))
        self.assertEqual(sorted(got), ["17-3", "24-9"])

    def test_変更が無ければコミットしない(self):
        self.assertEqual(runner.save(self.pc, "pc", self.quiet), "変更なし")


class TestEncoding(Base):
    """文字コードと改行（仕様 §8 の4つ目・5つ目）"""

    def test_日本語が化けない(self):
        d = day(picks=[pick()])
        d["picks"][0]["place"] = "びわこ"
        d["picks"][0]["note"] = "大村・宮島 — 波0〜2cm"
        write(os.path.join(self.pc, "history.json"), {"days": [d]})
        runner.save(self.pc, "pc", self.quiet)

        got = read(os.path.join(self.pc, "history.json"))["days"][0]["picks"][0]
        self.assertEqual(got["place"], "びわこ")
        self.assertEqual(got["note"], "大村・宮島 — 波0〜2cm")

        sh(self.other, "git", "pull", "-q", "origin", "main")
        far = read(os.path.join(self.other, "history.json"))["days"][0]["picks"][0]
        self.assertEqual(far["note"], "大村・宮島 — 波0〜2cm")   # 向こうでも化けない

    def test_改行はLFのまま(self):
        write(os.path.join(self.pc, "state/notified_20260920.json"), ["24-9"])
        runner.save(self.pc, "pc", self.quiet)
        with open(os.path.join(self.pc, "state/notified_20260920.json"), "rb") as f:
            self.assertNotIn(b"\r\n", f.read())

    def test_触っていないファイルに差分が出ない(self):
        write(os.path.join(self.pc, "state/notified_20260920.json"), ["24-9"])
        runner.save(self.pc, "pc", self.quiet)
        write(os.path.join(self.pc, "state/notified_20260921.json"), ["17-3"])
        runner.save(self.pc, "pc", self.quiet)
        changed = sh(self.pc, "git", "show", "--stat", "--oneline", "HEAD").splitlines()
        self.assertTrue(any("notified_20260921" in ln for ln in changed))
        self.assertFalse(any("notified_20260920" in ln for ln in changed))


class TestSafety(Base):
    """データ以外の編集を消さないこと"""

    def test_コードを直しかけていたら取り込みを見送る(self):
        # 手元で merge_history.py を直しかけている状態を作る
        path = os.path.join(self.pc, "merge_history.py")
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n# 直しかけ\n")
        # リモートは先に進んでいる
        write(os.path.join(self.other, "history.json"), {"days": [day(date="20260919")]})
        sh(self.other, "git", "add", "-A")
        sh(self.other, "git", "commit", "-q", "-m", "remote")
        sh(self.other, "git", "push", "-q", "origin", "main")

        self.assertFalse(runner.onto_remote(self.pc, self.quiet))
        with open(path, encoding="utf-8") as f:
            self.assertIn("直しかけ", f.read())      # 消えていない

    def test_追跡していないファイルは邪魔しない(self):
        write(os.path.join(self.pc, "logs/yosou_20260920.log"), {"a": 1})
        self.assertEqual(runner.dirty_outside_data(self.pc), [])
        self.assertTrue(runner.onto_remote(self.pc, self.quiet))

    def test_データの変更は邪魔しない(self):
        write(os.path.join(self.pc, "history.json"), {"days": [day()]})
        write(os.path.join(self.pc, "state/notified_20260920.json"), ["24-9"])
        self.assertEqual(runner.dirty_outside_data(self.pc), [])


class TestMain(Base):
    """入口の終了コード"""

    def test_v24のフォルダでなければ3(self):
        self.assertEqual(runner.main(["yosou", "--repo", self.dir]), 3)

    def test_もう動いていたら2(self):
        logs = os.path.join(self.dir, "logs")
        with runner.Lock(os.path.join(logs, "yosou.lock"), log=self.quiet):
            code = runner.main(["yosou", "--repo", self.pc, "--log-dir", logs,
                                "--no-push"])
        self.assertEqual(code, 2)


class TestLock(Base):
    """二重起動の防止（仕様 §8 の2つ目）"""

    def path(self):
        return os.path.join(self.dir, "logs", "yosou.lock")

    def test_2つ目は動かない(self):
        with runner.Lock(self.path(), log=self.quiet) as first:
            self.assertTrue(first)
            with runner.Lock(self.path(), log=self.quiet) as second:
                self.assertFalse(second)

    def test_終わればまた取れる(self):
        with runner.Lock(self.path(), log=self.quiet) as a:
            self.assertTrue(a)
        with runner.Lock(self.path(), log=self.quiet) as b:
            self.assertTrue(b)

    def test_古いロックは無視する(self):
        os.makedirs(os.path.dirname(self.path()), exist_ok=True)
        with open(self.path(), "w") as f:
            f.write("999999 0\n")
        os.utime(self.path(), (0, 0))            # 大昔に作られたことにする
        with runner.Lock(self.path(), stale_minutes=60, log=self.quiet) as got:
            self.assertTrue(got)


class TestUnion(unittest.TestCase):
    """通知済みの和集合だけを直接見る"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_足し合わせる(self):
        a, b = os.path.join(self.dir, "a.json"), os.path.join(self.dir, "b.json")
        write(a, ["24-9", "17-3"])
        write(b, ["17-3", "14-5"])
        self.assertTrue(runner.union_notified(a, b, b))
        self.assertEqual(sorted(read(b)), ["14-5", "17-3", "24-9"])

    def test_形が違えば足さない(self):
        a, b = os.path.join(self.dir, "a.json"), os.path.join(self.dir, "b.json")
        write(a, {"これは": "辞書"})
        write(b, ["24-9"])
        self.assertFalse(runner.union_notified(a, b, b))
        self.assertEqual(read(b), ["24-9"])


class TestTaskArgs(unittest.TestCase):
    """本体の呼び出しが .github/workflows/*.yml と合っているか"""

    class Fake(runner.Task):
        def __init__(self, **kw):
            super().__init__(repo=".", log=lambda *a: None, **kw)
            self.calls = []

        def run_py(self, *args, check=True):
            self.calls.append(list(args))
            return True

    def test_yosouはbudget150(self):
        t = self.Fake()
        msg = t.yosou()
        self.assertEqual(t.calls, [["yosou.py", "--budget", "150"]])
        self.assertTrue(msg.startswith("state: "))

    def test_dryなら通知しない(self):
        t = self.Fake(dry=True)
        t.yosou()
        self.assertIn("--dry", t.calls[0])

    def test_prefetch(self):
        t = self.Fake()
        self.assertTrue(t.prefetch().startswith("prefetch: "))
        self.assertEqual(t.calls, [["prefetch.py"]])

    def test_motorはkfileとrawを渡す(self):
        t = self.Fake(v22="/boat/v22")
        t.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t.repo, True)
        write(os.path.join(t.repo, "motor/latest.json"),
              {"date": "20260920", "values": {str(i): 1 for i in range(600)}})
        msg = t.motor()
        self.assertEqual(t.calls[0][:2], ["motor.py", "--kfile"])
        self.assertIn("--days", t.calls[0])
        self.assertEqual(t.calls[1][0], "settle.py")
        self.assertIn("kfile", t.calls[1][2])
        self.assertIn("raw", t.calls[1][4])
        self.assertTrue(msg.startswith("motor+settle: "))

    def test_モーター純度が少なければ止める(self):
        t = self.Fake(v22="/boat/v22")
        t.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t.repo, True)
        write(os.path.join(t.repo, "motor/latest.json"),
              {"date": "20260920", "values": {"1": 1}})
        with self.assertRaises(RuntimeError):
            t.motor()


class TestWorkflows(unittest.TestCase):
    """PC に移した3つが GitHub でも定期で動いていないか

    両方が定期で動く日を作ると、同じレースを二重に通知し、
    自動投票が二重に買いに行く。消したものが戻っていないかを見張る。
    """

    def on_block(self, name):
        """その .yml の on: の塊だけを取り出す（字下げが続く間）"""
        path = os.path.join(V24, ".github", "workflows", name)
        lines = io.open(path, encoding="utf-8").read().splitlines()
        out, inside = [], False
        for line in lines:
            if line.startswith("on:"):
                inside = True
                continue
            if inside:
                if line and not line[0].isspace():
                    break
                if line.lstrip().startswith("#"):
                    continue    # 注釈に書いた "schedule:" を拾わない
                out.append(line)
        self.assertTrue(inside, f"{name} に on: が無い")
        return "\n".join(out)

    def test_PCに移した3つは定期で動かない(self):
        for name in ("yosou.yml", "motor.yml", "prefetch.yml"):
            block = self.on_block(name)
            self.assertNotIn(
                "schedule:", block,
                f"{name} に schedule: が戻っている。"
                "PC と両方が定期で動くと二重通知・二重投票になる")
            self.assertIn("workflow_dispatch:", block,
                          f"{name} の手動起動が無い（予備運転ができない）")

    def test_見張りと夜の集計は残っている(self):
        for name in ("watchdog.yml", "daily.yml"):
            self.assertIn("schedule:", self.on_block(name),
                          f"{name} の定期実行が消えている")


if __name__ == "__main__":
    unittest.main(verbosity=2)
