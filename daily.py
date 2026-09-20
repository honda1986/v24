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
# ★2026-09-20 に帯を「p/q>1.15 ＋ 波・風の足切りを廃止」に変えた
#   （band_howto.md §13〜§14）。1.097＋足切りありのときの検証値は 1日6.6レース。
#   新しい設定では
#     バックテスト（確定オッズ・498日）          1日 4.9レース（買えた日 97%）
#     ↑を本番の目減り率で割り引いた見込み        1日 2.0レース
#   本番は締切前オッズで判定するぶん p/q が下がる（本番20日の再生では
#   バックテストの約0.4倍だった）。daily.py が見比べる相手は後者を使う。
#   実績が貯まったら測り直すこと。
#   ★2026-09-21: 窓を 4〜15分 に狭め、しきい値を 1.14 に下げた。
#     窓が狭いぶん1レースを見る回数が 8〜9回 → 3〜4回 に減るので買い目も減り、
#     しきい値を下げたぶんで相殺する形。どちらがどれだけ効くかは実測待ちで、
#     記録に "left"（締切まで何分で判定したか）を残し始めた。
#     見込みは据え置き、2週間ぶん貯まったら測り直すこと。
EXPECT_RACES = 2.0      # 1日あたり買い目が出るレース数（本番相当の見込み）
# ★買い目ゼロの日は普通にある。足切りを外して 97% の日に買い目が出る見込みだが、
#   本番の目減りを考えるとゼロの日は 1〜2割は出る。3日連続で警報を出すと
#   鳴りやすいので、実際に「壊れている」と言える長さまで伸ばす。
#   ほかの警報（yosou が動いていない／対象レースがゼロ／データ欠）が
#   本来の故障検知を担う。
ZERO_DAYS = 10


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
    runs = (day or {}).get("runs", 0)
    last = (day or {}).get("last_run", "—")
    hour = datetime.now(JST).hour

    # ★数え方に注意。
    #   skipped は「見送った回数」で、同じレースを何回も見るので重複する。
    #   しかも取れなかったレースは次の回もまた見に行くのに対し、
    #   買えたレースは done に入って二度と見ない。つまり skipped だけで
    #   割合を出すと、失敗を過大に見積もる。
    #   races は (場,R) で1件に畳んであるので、こちらで割合を出す。
    races = (day or {}).get("races") or []
    LACK = ("気象が取れない", "今節成績が取れません", "出走表が取れません",
            "出走表の形が違います", "オッズが取れません")
    if races:
        looked = len(races)
        lack = sum(1 for r in races if r.get("status") in LACK)
        by = {}
        for r in races:
            by[r.get("status") or "?"] = by.get(r.get("status") or "?", 0) + 1
    else:       # 旧い記録（races が無い日）は従来の数え方に落とす
        looked = len(picks) + sum(skipped.values())
        lack = skipped.get("データ欠", 0)
        by = dict(skipped)

    # 直近 ZERO_DAYS 日、買い目が出たか（先頭3日はメッセージにも出す）
    recent = []
    for i in range(ZERO_DAYS):
        d = (datetime.strptime(date, "%Y%m%d") - timedelta(days=i)).strftime("%Y%m%d")
        recent.append(len((days.get(d) or {}).get("picks") or []))

    ana = (day or {}).get("ana") or []
    lines = [f"買い目 {len(picks)}レース "
             f"{sum(len(p['buys']) for p in picks)}点"]
    if ana:
        # ★穴側(試験)は帯とは別勘定。足し合わせて出さない（メモ §41）
        lines.append(f"穴側(試験) {len(ana)}レース "
                     f"{sum(len(p.get('buys') or []) for p in ana)}点")
    lines += [f"見たレース {looked}（重複を除いた実数）",
              f"実行 {runs}回（最後 {last}）"]
    for k, v in sorted(by.items(), key=lambda z: -z[1]):
        # 「買い」「穴のみ」は見送りではないので内訳に出さない
        if k not in ("買い", "穴のみ"):
            lines.append(f"  {k} {v}")

    # 異常の判定。「静かなだけ」と「壊れている」を分ける
    alarm = []
    # ★ミッドナイトは23時台まで走るので、それ以前は「まだ途中」とみなす
    early = hour < 23      # レースが終わる前に手で回した場合
    if runs == 0:
        alarm.append("yosou が1回も動いていない。ワークフローを確認すること")
    elif looked == 0 and not early:
        alarm.append(f"{runs}回動いたが、対象レースが1つも無かった。"
                     "締切時刻が取れていない可能性")
    elif lack and lack / max(looked, 1) > 0.3:
        alarm.append(f"データが取れないレースが{lack}/{looked}"
                     f"（{lack/looked*100:.0f}%）。取得元が不調")
    # ★「静かなだけ」と「壊れている」を分ける。1.15 では買い目ゼロの日が
    #   4割ほどあるので、連続の長さで見る（ZERO_DAYS の説明を参照）。
    if (len(picks) == 0 and sum(recent) == 0 and looked and not early
            and len(days) >= ZERO_DAYS):
        alarm.append(f"{ZERO_DAYS}日続けて買い目ゼロ。"
                     "ゼロの日自体は珍しくないが、この長さは想定外")

    title = (f"v24 {date[4:6]}/{date[6:8]} 今日の集計"
             if not alarm else f"★v24 {date[4:6]}/{date[6:8]} 異常")
    body = "\n".join(lines)
    if alarm:
        body += "\n\n★" + "\n★".join(alarm)
    else:
        body += (f"\n\n検証値は1日{EXPECT_RACES}レース。"
                 f"直近3日 {recent[2]}/{recent[1]}/{recent[0]}レース")
    if early:
        body += "\n(まだレース中の時間帯です。定期実行は23:50)"

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
