#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""runner.py -- 定期実行を PC で回すための包み

  python runner.py yosou      予想（3分おきに1回ずつ）
  python runner.py prefetch   当日の出走表を先取り
  python runner.py motor      モーター純度と、前日の結果の取り込み

GitHub Actions では、Python を呼ぶ前後の「取り込み・保存・push」を bash で
書いていた（yosou.yml の save()）。Windows には bash が無いので、それを
Python に移したもの。中身は save() と同じ順番・同じ考え方で、1か所だけ
良くしてある（notified を和集合にする。下の ★2 を見ること）。

1回の実行でやること:

  1. 二重起動を防ぐ（ロック。古いロックは無視する）
  2. リモートを取り込む（予備運転の記録を拾うため）
  3. 本体を動かす
  4. 変更があれば commit して push（失敗しても何も消さない）
  5. ログを残す

★1 git に JSON を混ぜさせない（メモ §26）
   history.json は1行の大きな JSON なので、git から見れば常に同じ行の衝突。
   rebase では直せず、-X theirs で片方を採ると settle の的中・払戻が消える。
   だから毎回リモートを土台に置き直し、自分のぶんを merge_history.py で
   意味を見て足す。rebase も merge も --force も使わない。

★2 notified は和集合にする
   yosou.yml の save() は state/ をローカルで上書きしていた。PC と GitHub の
   両方で動いた日は、片方の「通知済み」が消えて二重通知になる。
   ここでは両方を足し合わせる。どちらかで通知済みなら通知済み。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9), "JST")

# 取り込みと保存で面倒を見るもの。yosou.yml / motor.yml / prefetch.yml と同じ
DATA_DIRS = ("state", "cache", "motor")
DATA_FILES = ("history.json",)


def now_jst():
    return datetime.now(JST)


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------
# ★git に「人に聞く」を絶対にさせない（2026-09-20）
#   タスクスケジューラから動くときは画面が無い。GitHub の認証が要る状態で
#   push すると、パスワードを聞く窓を出せずに固まる。実機では1回目の push で
#   止まり、次の周が「まだ動いています」で全部飛ばされた。
#   聞かずに失敗させれば「push できず(次周に持ち越し)」で済む。
GIT_ENV = {
    "GIT_TERMINAL_PROMPT": "0",     # 端末で聞かない
    "GCM_INTERACTIVE": "never",     # Git Credential Manager の窓を出さない
    "GIT_ASKPASS": "",              # 外の入力窓も使わせない
    "SSH_ASKPASS": "",
}
GIT_TIMEOUT = 180                   # 念のための上限。ここまでで必ず戻る


def git(repo, *args, check=False, timeout=GIT_TIMEOUT):
    """git を1回叩く。(ok, 出力) を返す。止まらない・聞かない"""
    try:
        p = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, **GIT_ENV), timeout=timeout)
    except subprocess.TimeoutExpired:
        out = f"git {' '.join(args)}: {timeout}秒で戻ってこないので諦めました"
        if check:
            raise RuntimeError(out)
        return False, out
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.returncode == 0, (p.stdout or "") + (p.stderr or "")


def branch(repo):
    ok, out = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    name = out.strip()
    return name if ok and name and name != "HEAD" else "main"


def ensure_identity(repo):
    """コミットする人の名前。無ければ入れておく（PC では初回だけ）"""
    for key, val in (("user.name", "boat-pc"), ("user.email", "boat-pc@local")):
        ok, out = git(repo, "config", "--get", key)
        if not ok or not out.strip():
            git(repo, "config", key, val)


# --------------------------------------------------------------------------
# 取り込み（リモートを土台にして、自分の書いたぶんを載せ直す）
# --------------------------------------------------------------------------
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    """UTF-8 / 改行は LF で書く（Windows で CRLF になると全行差分になる）"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False)


def union_notified(mine_path, theirs_path, out_path):
    """通知済みの一覧を足し合わせる。どちらかで通知済みなら通知済み"""
    mine = load_json(mine_path, []) or []
    theirs = load_json(theirs_path, []) or []
    if not isinstance(mine, list) or not isinstance(theirs, list):
        return False
    merged = list(dict.fromkeys([*theirs, *mine]))   # 並びは残す。重複だけ落とす
    save_json(out_path, merged)
    return True


def snapshot(repo, tmp):
    """いま手元にある書き込みを退避する（reset --hard で消える前に）"""
    for d in DATA_DIRS:
        src = os.path.join(repo, d)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(tmp, d), dirs_exist_ok=True)
    for f in DATA_FILES:
        src = os.path.join(repo, f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(tmp, f))


def integrate(tmp, repo, log=print):
    """退避した自分のぶんを、リモートの上に意味を見て載せる

    - state/notified_*.json … 和集合（★2）
    - state/ のそれ以外, cache/, motor/ … ローカル優先
    - history.json … merge_history.py（★1）
    """
    for d in DATA_DIRS:
        src = os.path.join(tmp, d)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(repo, d)
        os.makedirs(dst, exist_ok=True)
        for name in sorted(os.listdir(src)):
            s, t = os.path.join(src, name), os.path.join(dst, name)
            if os.path.isdir(s):
                shutil.copytree(s, t, dirs_exist_ok=True)
                continue
            if d == "state" and name.startswith("notified_") and os.path.isfile(t):
                if union_notified(s, t, t):
                    continue          # 足し合わせた。上書きはしない
            shutil.copy2(s, t)

    mine = os.path.join(tmp, "history.json")
    out = os.path.join(repo, "history.json")
    if os.path.isfile(mine):
        p = subprocess.run([sys.executable, "merge_history.py", mine, out],
                           cwd=repo, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if p.returncode != 0:
            log(f"  history.json を統合できず、自分のぶんを使います: "
                f"{(p.stderr or '').strip()[:120]}")
            shutil.copy2(mine, out)
        elif p.stdout:
            log("  " + p.stdout.strip())


def dirty_outside_data(repo):
    """データ以外に手を加えたファイル（reset --hard で消えてしまうもの）

    ★GitHub は毎回まっさらな checkout なので起きなかったが、PC では
      コードを直しかけたまま定期実行が回ることがある。消してはいけない。
    """
    ok, out = git(repo, "status", "--porcelain")
    if not ok:
        return []
    names = []
    for line in out.splitlines():
        if not line or line.startswith("??"):      # 追跡していないものは消えない
            continue
        path = line[3:].strip().strip('"').split(" -> ")[-1]
        if path.split("/")[0] in DATA_DIRS or path in DATA_FILES:
            continue
        names.append(path)
    return names


def onto_remote(repo, log=print):
    """リモートを土台に置き直して、自分の書いたぶんを載せ直す

    fetch できなければ何もしない（ネットが無いときに手元を壊さないため）。
    データ以外に手を加えたファイルがあるときも、置き直さない（消さないため）。
    """
    dirty = dirty_outside_data(repo)
    if dirty:
        log("  ★データ以外に手を加えたファイルがあります: "
            + ", ".join(dirty[:5]) + ("…" if len(dirty) > 5 else ""))
        log("    消さないために、リモートの取り込みを見送ります"
            "（commit するか元に戻すと、また取り込みます）")
        return False
    br = branch(repo)
    ok, out = git(repo, "fetch", "-q", "origin", br)
    if not ok:
        log(f"  リモートを取れず（{out.strip()[:120]}）。手元のまま進みます")
        return False
    tmp = tempfile.mkdtemp(prefix="runner-")
    try:
        snapshot(repo, tmp)
        git(repo, "rebase", "--quit")          # 途中の rebase を解除
        git(repo, "checkout", "-q", "-B", br)
        git(repo, "reset", "-q", "--hard", f"origin/{br}")
        integrate(tmp, repo, log)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return True


def save(repo, message, log=print, push=True):
    """リモートを取り込んでから、変更を commit して push する

    ★push に失敗しても何も消さない。次の周がまた push する。
    """
    ensure_identity(repo)
    onto_remote(repo, log)
    br = branch(repo)
    for p in (*DATA_DIRS, *DATA_FILES):
        if os.path.exists(os.path.join(repo, p)):
            git(repo, "add", "-A", p)
    ok, _ = git(repo, "diff", "--cached", "--quiet")
    if ok:
        log("  変更なし")
        return "変更なし"
    git(repo, "commit", "-q", "-m", message)
    if not push:
        log("  commit だけしました（push しない指定）")
        return "commit"
    ok, out = git(repo, "push", "-q", "origin", f"HEAD:{br}")
    if not ok:
        log(f"  push できず(次周に持ち越し): {out.strip()[:200]}")
        low = out.lower()
        if ("authentication" in low or "could not read" in low
                or "terminal prompts disabled" in low or "403" in low):
            log("  ★GitHub のログインがまだです。画面のある窓で1回 push して"
                "ください:  cd C:\\boat\\v24 && git push origin HEAD:main")
        return "push できず"
    log("  push しました")
    return "push"


# --------------------------------------------------------------------------
# 二重起動の防止
# --------------------------------------------------------------------------
class Lock:
    """同じタスクが二重に動かないようにする。古いロックは無視する"""

    def __init__(self, path, stale_minutes=60, log=print):
        self.path = path
        self.stale = stale_minutes * 60
        self.log = log
        self.taken = False

    def __enter__(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(f"{os.getpid()} {int(time.time())}\n")
                self.taken = True
                return True
            except FileExistsError:
                age = time.time() - os.path.getmtime(self.path)
                if age < self.stale:
                    self.log(f"  もう動いています（{self.path} が {age/60:.0f}分前から）。"
                             "この回は何もしません")
                    return False
                self.log(f"  古いロックを捨てます（{age/60:.0f}分前）")
                try:
                    os.unlink(self.path)
                except OSError:
                    return False
        return False

    def __exit__(self, *exc):
        if self.taken:
            try:
                os.unlink(self.path)
            except OSError:
                pass
        return False


# --------------------------------------------------------------------------
# タスク
# --------------------------------------------------------------------------
class Task:
    """本体を動かすところ。引数は .github/workflows/*.yml と同じにしてある"""

    def __init__(self, repo, python=None, v22=None, dry=False,
                 timeout=600, log=print):
        self.repo = repo
        self.python = python or sys.executable
        self.v22 = v22
        self.dry = dry
        self.timeout = timeout
        self.log = log

    def run_py(self, *args, check=True):
        cmd = [self.python, *args]
        self.log("  $ " + " ".join(args))
        try:
            p = subprocess.run(cmd, cwd=self.repo, timeout=self.timeout,
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            self.log(f"  ★{self.timeout}秒で切りました")
            if check:
                raise
            return False
        for line in (p.stdout or "").splitlines():
            self.log("  | " + line)
        if p.returncode != 0:
            self.log(f"  ★失敗 (code {p.returncode}) "
                     + (p.stderr or "").strip()[:300])
            if check:
                raise RuntimeError(f"{args[0]} が失敗しました")
            return False
        return True

    # yosou.yml: python yosou.py --budget 150
    def yosou(self):
        args = ["yosou.py", "--budget", "150"]
        if self.dry:
            args.append("--dry")
        self.run_py(*args, check=False)     # 失敗しても次の周が拾う
        return f"state: {now_jst():%H%M}"

    # prefetch.yml: python prefetch.py || true
    def prefetch(self):
        self.run_py("prefetch.py", check=False)
        return f"prefetch: {now_jst():%Y%m%d-%H%M}"

    # motor.yml: v22 を取り込む → motor.py → settle.py
    def motor(self):
        if self.v22 and os.path.isdir(os.path.join(self.v22, ".git")):
            ok, out = git(self.v22, "pull", "-q", "--ff-only")
            self.log("  v22 を取り込みました" if ok
                     else f"  v22 を取り込めず: {out.strip()[:120]}")
        kfile = os.path.join(self.v22 or "../v22", "kfile")
        raw = os.path.join(self.v22 or "../v22", "raw")
        # ★settle は motor と関係が無いので、motor が転んでも必ず走らせる。
        #   前は motor.py の失敗や「500人未満」で例外を投げ、settle まで
        #   届かなかった。結果（的中・払戻）が入らない原因になる。
        bad = None
        try:
            self.run_py("motor.py", "--kfile", kfile, "--days", "400",
                        "--out", "motor/latest.json")
            # motor.yml と同じ検算。500人に満たなければ止める
            j = load_json(os.path.join(self.repo, "motor/latest.json"), {})
            n = len(j.get("values") or {})
            self.log(f"  モーター純度 {j.get('date')} {n}人")
            if n < 500:
                raise RuntimeError(f"モーター純度が {n}人 しかありません（500人未満）")
        except Exception as e:
            bad = e
            self.log(f"  ★motor は失敗しましたが settle は続けます: {e}")
        self.run_py("settle.py", "--kfile", kfile, "--raw", raw, check=False)
        if bad:
            raise bad
        return f"motor+settle: {now_jst():%Y%m%d}"


TASKS = {"yosou": 600, "prefetch": 1500, "motor": 3000}    # 打ち切りの秒数


# --------------------------------------------------------------------------
class Log:
    """1行ずつ画面とファイルに書く"""

    def __init__(self, path):
        self.path = path

    def __call__(self, text):
        line = f"{now_jst():%H:%M:%S} {text}"
        print(line, flush=True)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
        except OSError:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="定期実行を PC で回す")
    ap.add_argument("task", choices=sorted(TASKS))
    ap.add_argument("--repo", default=".", help="v24 のフォルダ（既定は今いる場所）")
    ap.add_argument("--v22", default="../v22", help="v22 のフォルダ（motor で使う）")
    ap.add_argument("--log-dir", default="logs")
    ap.add_argument("--python", default=None, help="本体を動かす python")
    ap.add_argument("--timeout", type=int, default=None, help="打ち切りの秒数")
    ap.add_argument("--dry", action="store_true", help="yosou を通知せずに動かす")
    ap.add_argument("--no-push", dest="push", action="store_false", default=True)
    args = ap.parse_args(argv)

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(os.path.join(repo, ".git")):
        print(f"v24 のフォルダではありません: {repo}")
        return 3

    log_dir = args.log_dir if os.path.isabs(args.log_dir) \
        else os.path.join(repo, args.log_dir)
    log = Log(os.path.join(log_dir, f"{args.task}_{now_jst():%Y%m%d}.log"))
    timeout = args.timeout or TASKS[args.task]

    # ★古すぎる値にしないこと。強制終了されるとロックのファイルが残るので、
    #   長すぎるとその間ずっと「まだ動いています」で何もしなくなる。
    #   タスク側の打ち切り（yosou は10分）より少しだけ長ければよい。
    with Lock(os.path.join(log_dir, f"{args.task}.lock"),
              stale_minutes=max(15, timeout // 60 + 5), log=log) as got:
        if not got:
            return 2
        log(f"=== {args.task} 開始 ===")
        task = Task(repo, python=args.python, v22=os.path.abspath(args.v22),
                    dry=args.dry, timeout=timeout, log=log)
        onto_remote(repo, log)              # 予備運転のぶんを取り込む
        try:
            message = getattr(task, args.task)()
        except Exception as e:
            log(f"★{type(e).__name__}: {e}")
            save(repo, f"{args.task}(途中まで): {now_jst():%H%M}", log, push=args.push)
            return 1
        save(repo, message, log, push=args.push)
        log(f"=== {args.task} 終わり ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
