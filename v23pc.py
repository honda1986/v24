#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v23pc.py -- PC で v23 の予想も回す（2026-11-19〜。band_howto.md §36）

★v23 は GitHub Actions で回していたが、2026-11-19 から
    ・uchisankaku（出走表の取り元）が空になった → v23 は公式の出走表で代える（v23 の officialpage.py）
    ・公式（boatrace.jp）が GitHub からの接続を断る（Access Denied）→ 締切時刻・オッズも取れない
  PC からは公式に届くので、v24 の yosou の回のあとに v23 も回す（runner.py から呼ぶ）。

  1. C:\\boat\\v23 に boatrace-appV23 を置く（無ければ clone。毎回リモートに合わせる）
  2. 1時間ごとに v22 の Kファイルからモーター純度（motor.py）
  3. 15分ごとに yosou.py（GitHub の yosou.yml の1周と同じ）
  4. yosou/pc_alive.json（心拍）を足して commit → push。GitHub の yosou.yml は心拍が新しければ休む

  通知の宛先は環境変数 NTFY_TOPIC_V23、無ければ NTFY_TOPIC（v24 と同じ）。
  ★boat_yosou のタスクは10分で切られる。v24 の回で使った残りの時間だけ回す（MIN_LEFT 未満なら次の回へ）
"""
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
URL = "https://github.com/honda1986/boatrace-appV23.git"
EVERY_MIN = 15            # yosou.py を回す間隔（GitHub と同じ）
MOTOR_EVERY_MIN = 60      # モーター純度を作り直す間隔（前日の Kファイルは朝9〜10時ごろ届く）
TASK_LIMIT = 600          # boat_yosou のタスクの打ち切り（register_tasks.ps1 の10分）
MIN_LEFT = 240            # 残りがこれより短ければ、この回は回さない
FILES = ("yosou/data.json", "yosou/days", "yosou/history.json", "yosou/races.json",
         "yosou/pc_alive.json")


def now_jst():
    return datetime.now(JST)


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def minutes_since(iso, now):
    try:
        return (now - datetime.fromisoformat(iso)).total_seconds() / 60
    except (TypeError, ValueError):
        return None


def due(state, key, every, now):
    m = minutes_since(state.get(key), now)
    return m is None or m >= every - 1          # 3分おきの回なので1分の余裕


def maybe_run(v24_repo, v22_dir, python, log, log_dir, started, git, push=True):
    """v24 の yosou の回のあとに呼ぶ。15分たっていて時間が残っていれば v23 を1周回す。
    git は runner.git（(ok, 出力) を返す）。何があっても例外は外に出さない。

    ★PC のログは GitHub に上がらないので、回したときの結果を v24 の state/v23_pc.json に残す
      （次の周の push で上がる）。「★」の付いた行（失敗の理由）を最後の5行まで"""
    bad = []

    def log2(msg):
        log(msg)
        if "★" in msg:
            bad.append(msg.strip()[:300])
    res = _run(v24_repo, v22_dir, python, log2, log_dir, started, git, push)
    if res not in ("まだ", "時間なし"):
        _save(os.path.join(v24_repo, "state", "v23_pc.json"),
              {"t": now_jst().isoformat(timespec="seconds"), "result": res, "bad": bad[-5:]})
    return res


def _run(v24_repo, v22_dir, python, log, log_dir, started, git, push):
    now = now_jst()
    sp = os.path.join(log_dir, "v23_state.json")
    st = _load(sp, {})
    if not due(st, "yosou", EVERY_MIN, now):
        return "まだ"
    left = TASK_LIMIT - (time.time() - started) - 60
    if left < MIN_LEFT:
        log(f"  v23: 残り{left:.0f}秒しかないので次の回へ")
        return "時間なし"
    d = os.path.join(os.path.dirname(os.path.abspath(v24_repo)), "v23")
    log(f"--- v23（{d}） ---")
    if not os.path.isdir(os.path.join(d, ".git")):
        ok, out = git(os.path.dirname(d), "clone", "-q", URL, d, timeout=300)
        log("  v23 を clone しました" if ok else f"  ★v23 を clone できず: {out.strip()[:200]}")
        if not ok:
            return "clone できず"
    # ★commit する名前。v24 は runner.py が入れているが、v23 の clone には無い。無いと commit が黙って失敗し、
    #   push は「送るものが無い」で成功に見える（2026-11-19 の初回がこれ）
    for key, val in (("user.name", "boat-pc"), ("user.email", "boat-pc@local")):
        if not git(d, "config", "--get", key)[0]:
            git(d, "config", key, val)
    ok, out = git(d, "fetch", "-q", "origin", "main")
    if ok:
        git(d, "reset", "-q", "--hard", "origin/main")       # このフォルダは v23 のためだけ。毎回リモートに合わせる
    else:
        log(f"  ★v23 を取り込めず（手元のまま回す）: {out.strip()[:120]}")

    def py(*args, timeout):
        env = dict(os.environ, PYTHONUTF8="1")
        env["NTFY_TOPIC"] = os.environ.get("NTFY_TOPIC_V23") or os.environ.get("NTFY_TOPIC", "")
        try:
            p = subprocess.run([python, *args], cwd=d, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", env=env, timeout=timeout)
        except subprocess.TimeoutExpired:
            log(f"  ★v23 {args[0]} は{timeout:.0f}秒で切りました")
            return False
        for line in (p.stdout or "").splitlines()[-25:]:
            log("  | " + line)
        if p.returncode != 0:
            log(f"  ★v23 {args[0]} が失敗 (code {p.returncode}) " + (p.stderr or "").strip()[-300:])
        return p.returncode == 0

    if due(st, "motor", MOTOR_EVERY_MIN, now):
        py("motor.py", "--kfile", os.path.join(v22_dir, "kfile"), "--days", "400", timeout=120)
        st["motor"] = now.isoformat(timespec="seconds")
    left = TASK_LIMIT - (time.time() - started) - 60
    py("yosou.py", timeout=max(60, left))
    st["yosou"] = now_jst().isoformat(timespec="seconds")
    _save(sp, st)
    # 心拍。GitHub の yosou.yml はこれが20分以内なら休む（両方が同時に書かないように）
    _save(os.path.join(d, "yosou", "pc_alive.json"), {"t": now_jst().isoformat(timespec="seconds")})
    for f in FILES:
        if os.path.exists(os.path.join(d, f)):
            git(d, "add", f)
    if git(d, "diff", "--cached", "--quiet")[0]:
        return "変更なし"
    ok, out = git(d, "commit", "-q", "-m", f"yosou: 更新 (PC {now_jst():%H%M})")
    if not ok:
        log(f"  ★v23 を commit できず: {out.strip()[:200]}")
        return "commit できず"
    if not push:
        return "commit だけ"
    for i in range(3):
        # history.json がぶつかったらこちらを採る（GitHub の yosou.yml と同じ。次の周回で集計し直す）
        if git(d, "pull", "-q", "--rebase", "--autostash", "-X", "theirs", "origin", "main")[0]:
            ok, out = git(d, "push", "-q", "origin", "HEAD:main")
            # ★「成功」でも本当に届いたかを確かめる（手元の HEAD がリモートに入ったか）
            if ok and git(d, "fetch", "-q", "origin", "main")[0] and \
                    git(d, "merge-base", "--is-ancestor", "HEAD", "origin/main")[0]:
                log("  v23 を push しました")
                return "push"
            if ok:
                log("  ★v23 の push は成功と返ったのに、リモートに入っていません")
                return "push できず"
            log(f"  ★v23 を push できず: {out.strip()[:200]}")
        else:
            git(d, "rebase", "--abort")
        time.sleep(5)
    return "push できず"
