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
HINT = "GitHub の Actions から yosou を手動実行できます。"


def _hhmm(text):
    try:
        h, m = str(text).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def judge(history, now, stale_minutes=STALE_MINUTES, start=START, end=END):
    """(鳴らすか, 本文) を返す。画面もネットも要らないので、そのまま試せる"""
    mins = now.hour * 60 + now.minute
    if not (_hhmm(start) <= mins <= _hhmm(end)):
        return False, f"時間外（{start}〜{end} だけ見張ります）"

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

    alert, body = judge(history, now, stale_minutes=args.stale)
    print(f"JST {now:%H:%M} / {'★警告' if alert else 'ふつう'}: "
          + body.replace("\n", " "))
    if alert:
        notify(args.ntfy, body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
