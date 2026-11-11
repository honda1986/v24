#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""standby.py -- PC が止まっているあいだ、GitHub Actions で代わりに回す（予備運転）

  python standby.py --check            引き継ぐべきかだけ判定する（GITHUB_OUTPUT に need=0/1）
  python standby.py --v22 v22src       引き継いで回す（PC が戻るか、時間切れまで）

yosou.yml が10分おきに起こす。PC が動いていれば --check で数秒で終わる。

引き継ぎの決まり（runner.py の PC_STALE_MIN / HANDOVER_MIN、pc/README.md §5）:

  1. PC の心拍（state/alive_pc.json）が PC_STALE_MIN 分より古ければ引き継ぐ
     ★PC は朝 7:57 まで yosou を回さないので、心拍が古いのは当たり前。
       見張るのは WATCH_FROM〜WATCH_TO だけ
  2. 毎周、まずリモートを取り込んで PC の心拍を見る。新しくなっていたら止まる
  3. 回しているあいだは state/alive_gh.json に active を立てる。
     PC はそれを見て予想を控え、心拍だけ push する → 2 で止まる → PC が再開
  4. 止まるとき（PC が戻った / 時間切れ）は active を下ろして push する

予想・保存は runner.py と同じもの（取り込み → 本体 → 統合して push）を使う。
PC の朝の仕事のうち motor（モーター純度・結果の取り込み）も、その日まだ誰も
やっていなければ1回だけやる。
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

import runner as R

WATCH_FROM, WATCH_TO = "08:10", "23:55"   # この時間だけ PC を見張って引き継ぐ
LOOP_SEC = 180                            # PC と同じ3分おき
MAX_MIN = 330                             # 1ジョブの長さ（Actions は6時間で切られる）
CHAIN_UNTIL = "23:30"                     # 時間切れがこれより前なら、次のジョブを起こす


def _mins(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_watch(now):
    return _mins(WATCH_FROM) <= now.hour * 60 + now.minute <= _mins(WATCH_TO)


def pc_minutes(repo, now):
    """PC が最後に動いてから何分か。分からなければ None

    ★alive_pc.json が無いのは、この仕組みが入った直後（PC がまだ新しい
      runner.py で1回も動いていない）だけ。そのときは history.json の
      今日の last_run で代える（GitHub が一度も動いていなければ PC のもの）。
    """
    m = R.alive_minutes(R.read_alive(repo, "pc"), now)
    if m is not None or R.read_alive(repo, "gh"):
        return m
    h = R.load_json(os.path.join(repo, "history.json"), {}) or {}
    day = next((d for d in h.get("days") or []
                if d.get("date") == now.strftime("%Y%m%d")), None)
    try:
        hh, mm = (int(x) for x in (day or {})["last_run"].split(":"))
    except (KeyError, ValueError, AttributeError):
        return None
    return now.hour * 60 + now.minute - (hh * 60 + mm)


def judge(repo, now, force=False):
    """(引き継ぐか, 理由)"""
    if force:
        return True, "手動で引き継ぎ（force）"
    if not in_watch(now):
        return False, f"時間外（{WATCH_FROM}〜{WATCH_TO} だけ見張ります）"
    m = pc_minutes(repo, now)
    if m is not None and m <= R.PC_STALE_MIN:
        return False, f"PC が動いています（{m:.0f}分前）"
    return True, ("PC の記録がありません" if m is None
                  else f"PC が {m:.0f}分 止まっています")


def output(**kv):
    """GitHub Actions の次の段に値を渡す"""
    path = os.environ.get("GITHUB_OUTPUT")
    for k, v in kv.items():
        print(f"  {k}={v}")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{k}={v}\n")


def motor_light(task):
    """runner の motor から、時間のかかる直前情報の取り込み（collect_before）と
    snap_pack を抜いたもの。どちらも PC が戻った朝に3日さかのぼって埋める"""
    kfile, raw = task.pull_v22()
    task.run_py("motor.py", "--kfile", kfile, "--days", "400",
                "--out", "motor/latest.json", check=False)
    task.run_py("settle.py", "--kfile", kfile, "--raw", raw, check=False)
    task.run_py("calib.py", "--kfile", kfile, check=False)
    # ★v22 の raw / tokuten が空の日の代わり（band_howto.md §31）。前日の分だけ
    d = (R.now_jst() - R.timedelta(days=1)).strftime("%Y%m%d")
    task.run_py("collect_raw.py", "--date", d, "--kfile", kfile, "--raw", raw,
                "--tokuten", os.path.join(os.path.dirname(kfile), "tokuten"), check=False)


def chores(repo, task, log):
    """朝の仕事。その日まだ PC も GitHub もやっていなければ1回だけ"""
    today = R.now_jst().strftime("%Y%m%d")
    # ★prefetch はやらない。予備運転では info.kyotei.fun が届かないことが多く、
    #   そのとき全レースを公式から取ると30分近く予想が止まる。
    #   窓に入ったレースは yosou.racecard が1件ずつ公式で代える
    for name, run in (("motor", motor_light),):
        if any(R.read_alive(repo, h).get(name) == today for h in ("pc", "gh")):
            continue
        log(f"--- 今日の {name} がまだなので代わりにやります ---")
        try:
            run(task)
            R.touch_alive(repo, "gh", active=True, **{name: today})
        except Exception as e:                 # 朝の仕事が転んでも予想は回す
            log(f"  ★{name} は失敗: {e}")
        R.save(repo, f"standby {name}: {R.now_jst():%H%M}", log)


def loop(repo, v22, force, log):
    t0 = time.time()
    now = R.now_jst()
    end = t0 + MAX_MIN * 60
    last = now.replace(hour=23, minute=59, second=0, microsecond=0).timestamp()
    end = min(end, last)
    log(f"=== 予備運転 開始（{datetime.fromtimestamp(end, R.JST):%H:%M} まで）===")
    task = R.Task(repo, v22=v22, timeout=R.TASKS["yosou"], log=log)
    reason, did_chores, n = "time", False, 0
    while time.time() < end:
        t1 = time.time()
        R.onto_remote(repo, log)
        go, why = judge(repo, R.now_jst(), force)
        if not go:
            log(f"  {why}。予備運転を終わります")
            reason = "pc" if why.startswith("PC") else "out"
            break
        R.touch_alive(repo, "gh", active=True)
        n += 1
        log(f"--- {n}回目  {why} ---")
        task.yosou()
        R.touch_alive(repo, "gh", active=True)
        R.save(repo, f"standby: {R.now_jst():%H%M}", log)
        # ★朝の仕事は1周目の予想のあと（締切の近いレースを先に拾う）
        if not did_chores:
            did_chores = True
            mtask = R.Task(repo, v22=v22, timeout=R.TASKS["motor"], log=log)
            chores(repo, mtask, log)
        wait = LOOP_SEC - (time.time() - t1)
        if time.time() + max(wait, 0) >= end:
            break
        if wait > 0:
            time.sleep(wait)
    # ★判定時オッズ（snap/）は git に入らないので、終わる前に今日のぶんをまとめる
    task.run_py("snap_pack.py", "--date", R.now_jst().strftime("%Y%m%d"), check=False)
    R.onto_remote(repo, log)
    R.touch_alive(repo, "gh", active=False)
    R.save(repo, f"standby 終わり: {R.now_jst():%H%M}", log)
    chain = reason == "time" and R.now_jst().strftime("%H:%M") < CHAIN_UNTIL
    log(f"=== 予備運転 終わり（{n}回。"
        f"{ {'pc': 'PC が戻った', 'out': '見張る時間の外'}.get(reason, '時間切れ') }）===")
    output(chain=int(chain))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="PC が止まっているあいだの予備運転")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--v22", default="v22src")
    ap.add_argument("--check", action="store_true", help="引き継ぐべきかだけ見る")
    ap.add_argument("--force", action="store_true", help="PC が動いていても引き継ぐ")
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)
    log = R.Log(os.path.join(repo, "logs", f"standby_{R.now_jst():%Y%m%d}.log"))
    if args.check:
        go, why = judge(repo, R.now_jst(), args.force)
        log(f"JST {R.now_jst():%H:%M}  {'★引き継ぐ' if go else 'このまま'}: {why}")
        output(need=int(go))
        return 0
    os.environ.setdefault("PYTHONUTF8", "1")
    return loop(repo, os.path.abspath(args.v22), args.force, log)


if __name__ == "__main__":
    sys.exit(main())
