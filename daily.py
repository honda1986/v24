#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily.py -- 1日の終わりに、その日の集計を必ず通知する

★これが無いと「静かに壊れている」に気づけない。
  買い目ゼロは正常な状態でもあるので、通知が来ないだけでは
  「今日は無かった」のか「壊れて動いていない」のか区別できない。
  実際、オッズの解析が壊れて3日間ゼロだったのに誰も気づけなかった。

  検証値では 1日6.6レース・8.8点。0レースの日は2.5%しかない。
  つまり2日続けてゼロなら、まず壊れていると考えてよい。

  python daily.py            # 今日ぶん
  python daily.py --date 20260824
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
SITE = "history.json"
EXPECT_RACES = 6.6      # 検証値。1日あたり買い目が出るレース数


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--ntfy", default=os.environ.get("NTFY_TOPIC", ""))
    args = ap.parse_args()
    date = args.date or datetime.now(JST).strftime("%Y%m%d")

    h = load(SITE, {}) or {}
    days = {d["date"]: d for d in (h.get("days") or [])}
    day = days.get(date)
    picks = (day or {}).get("picks") or []
    skipped = (day or {}).get("skipped") or {}
    looked = len(picks) + sum(skipped.values())
    lack = skipped.get("データ欠", 0)

    # 直近3日、買い目が出たか
    recent = []
    for i in range(3):
        d = (datetime.strptime(date, "%Y%m%d") - timedelta(days=i)).strftime("%Y%m%d")
        recent.append(len((days.get(d) or {}).get("picks") or []))

    lines = [f"買い目 {len(picks)}レース "
             f"{sum(len(p['buys']) for p in picks)}点",
             f"見たレース {looked}"]
    for k, v in sorted(skipped.items(), key=lambda z: -z[1]):
        lines.append(f"  {k} {v}")

    # 異常の判定。「静かなだけ」と「壊れている」を分ける
    alarm = []
    if looked == 0:
        alarm.append("1レースも見ていない。ワークフローが動いていない")
    elif lack and lack / max(looked, 1) > 0.3:
        alarm.append(f"データが取れないレースが{lack/looked*100:.0f}%。取得元が不調")
    if len(picks) == 0 and sum(recent) == 0 and looked:
        alarm.append("3日続けて買い目ゼロ。検証値では0.0016%しか起きない")

    title = (f"v24 {date[4:6]}/{date[6:8]} 今日の集計"
             if not alarm else f"★v24 {date[4:6]}/{date[6:8]} 異常")
    body = "\n".join(lines)
    if alarm:
        body += "\n\n★" + "\n★".join(alarm)
    else:
        body += (f"\n\n検証値は1日{EXPECT_RACES}レース。"
                 f"直近3日 {recent[2]}/{recent[1]}/{recent[0]}レース")

    print(title)
    print(body)

    if not args.ntfy:
        print("\n(ntfy トピック未設定なので送りません)")
        return 1 if alarm else 0
    import requests
    try:
        r = requests.post("https://ntfy.sh",
                          json={"topic": args.ntfy, "title": title, "message": body,
                                "priority": 4 if alarm else 2,
                                "tags": ["rotating_light"] if alarm else ["bar_chart"]},
                          timeout=15)
        print(f"\nntfy {r.status_code}")
    except requests.RequestException as e:
        print(f"\nntfy 失敗 {type(e).__name__}")
    return 1 if alarm else 0


if __name__ == "__main__":
    raise SystemExit(main())
