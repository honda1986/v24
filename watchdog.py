#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watchdog.py -- PC が止まっていないかを GitHub から見張る

日中に PC が止まったら1時間以内に知らせるためのもの。
history.json を読むだけで、commit も push もしない。

判定（仕様 §5-3）:

  1. いまが 8:40〜23:10 の外なら、何もしない
  2. 今日の日付が days に無い      → 「今日は一度も動いていません」
  3. last_run が無い / 30分以上前  → 「◯分止まっています」
  4. それ以外は何もしない（正常なときに鳴らさない）

★push が失敗し続けているだけでも警告が出る。文面をそう書いてある。
★止まっている間は毎時鳴る。気づくまで鳴らすのが目的。
★2026-11-04 から、PC が止まると GitHub が自動で予備運転する（standby.py）。
  予備運転も history.json の last_run を進めるので、PC の心拍
  （state/alive_pc.json）があればそちらで判定する。予備運転が回っているかも書く。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9), "JST")

START, END = "08:40", "23:10"      # この時間だけ見張る
STALE_MINUTES = 30                 # これ以上あいたら止まっているとみなす
TITLE = "★PC停止の疑い"
HINT = ("PC が止まっているあいだは GitHub が自動で予備運転します"
        "（Actions の yosou。手動実行もできます）。")
HANDOVER_MIN = 8                   # runner.py と同じ。予備運転の心拍がこれ以内なら回っている


def _hhmm(text):
    try:
        h, m = str(text).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _age(alive, now):
    try:
        return (now - datetime.fromisoformat(alive["t"])).total_seconds() / 60
    except (KeyError, TypeError, ValueError):
        return None


def standby_line(alive_gh, now):
    m = _age(alive_gh or {}, now)
    if (alive_gh or {}).get("active") and m is not None and m < HANDOVER_MIN:
        return "いまは GitHub が予備運転しています（予想と通知は続いています）。"
    return "GitHub の予備運転はまだ回っていません（10分おきに確かめています）。"


def judge(history, now, stale_minutes=STALE_MINUTES, start=START, end=END,
          alive_pc=None, alive_gh=None):
    """(鳴らすか, 本文) を返す。画面もネットも要らないので、そのまま試せる"""
    mins = now.hour * 60 + now.minute
    if not (_hhmm(start) <= mins <= _hhmm(end)):
        return False, f"時間外（{start}〜{end} だけ見張ります）"

    # ★PC の心拍があればそれで見る（予備運転も last_run を進めるため）
    gap = _age(alive_pc or {}, now)
    if gap is not None:
        last = datetime.fromisoformat(alive_pc["t"]).astimezone(JST)
        if gap > stale_minutes:
            return True, (f"PC が {gap:.0f}分 止まっています（最後に動いたのは "
                          f"{last:%m/%d %H:%M}）。\n"
                          "PC が止まっているか、push できていません。\n"
                          + standby_line(alive_gh, now) + "\n" + HINT)
        return False, f"正常（PC が最後に動いたのは {last:%H:%M}、{max(gap, 0):.0f}分前）"

    date = now.strftime("%Y%m%d")
    days = (history or {}).get("days") or []
    day = next((d for d in days if isinstance(d, dict) and d.get("date") == date),
               None)
    if day is None:
        return True, (f"今日（{date}）は一度も動いていません。\n"
                      "PC が止まっているか、push できていません。\n" + HINT)

    last = _hhmm(day.get("last_run"))
    if last is None:
        return True, ("今日の最後に動いた時刻が記録されていません。\n"
                      "PC が止まっているか、push できていません。\n" + HINT)

    gap = mins - last
    if gap > stale_minutes:
        return True, (f"{gap}分 止まっています（最後に動いたのは "
                      f"{day.get('last_run')}）。\n"
                      "PC が止まっているか、push できていません。\n" + HINT)
    return False, f"正常（最後に動いたのは {day.get('last_run')}、{max(gap, 0)}分前）"


def notify(topic, body, title=TITLE, priority=5):
    if not topic:
        print("(ntfy トピック未設定なので送りません)")
        return False
    try:
        import requests
        r = requests.post("https://ntfy.sh",
                          json={"topic": topic, "title": title, "message": body,
                                "priority": priority, "tags": ["warning"]},
                          timeout=15)
        print(f"ntfy {r.status_code}")
        return r.status_code < 300
    except Exception as e:                      # 通知の失敗で落とさない
        print(f"ntfy 失敗 {type(e).__name__}")
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="PC が止まっていないか見張る")
    ap.add_argument("--history", default="history.json")
    ap.add_argument("--state", default="state", help="心拍（alive_pc.json）の場所")
    ap.add_argument("--ntfy", default=os.environ.get("NTFY_TOPIC", ""))
    ap.add_argument("--now", default=None, help="JST の HH:MM（試すとき用）")
    ap.add_argument("--stale", type=int, default=STALE_MINUTES)
    args = ap.parse_args(argv)

    now = datetime.now(JST)
    if args.now:
        h, m = args.now.split(":")
        now = now.replace(hour=int(h), minute=int(m))

    try:
        with open(args.history, encoding="utf-8") as f:
            history = json.load(f)
    except (OSError, ValueError) as e:
        print(f"history.json を読めません: {e}")
        return 0                                # 見張りが落ちても困るだけ

    def alive(host):
        try:
            with open(os.path.join(args.state, f"alive_{host}.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    alert, body = judge(history, now, stale_minutes=args.stale,
                        alive_pc=alive("pc"), alive_gh=alive("gh"))
    print(f"JST {now:%H:%M} / {'★警告' if alert else 'ふつう'}: "
          + body.replace("\n", " "))
    if alert:
        notify(args.ntfy, body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
