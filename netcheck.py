#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""netcheck.py -- 3つの取得元に、いまいる場所から届くかを確かめる

同じコードでも Colab では通り GitHub Actions では通らない、ということがある。
データセンターのIPを弾くサイトがあるため。どこで詰まっているかを切り分ける。

  python netcheck.py

Actions で走らせるときは workflow_dispatch から yosou.yml を使わず、
Actions タブ → yosou → Run workflow の前にこれを一度通しておくとよい。
"""
import socket
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

JST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "ja"}


def probe(name, url, need=5000):
    t0 = time.time()
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.encoding = r.apparent_encoding
        n = len(r.text)
        ms = int((time.time() - t0) * 1000)
        mark = "○" if (r.status_code == 200 and n >= need) else "✗"
        note = ""
        if r.status_code in (403, 429):
            note = "  ← 遮断されている（データセンターのIPを弾いている可能性）"
        elif r.status_code == 404:
            note = "  ← ページが無い（その日そのレースが未掲載かも）"
        elif r.status_code == 200 and n < need:
            note = f"  ← 中身が薄い（{need}文字未満）"
        print(f"  {mark} {name:<22} HTTP {r.status_code}  {n:>7,}文字  {ms:>5}ms{note}")
        return mark == "○"
    except requests.RequestException as e:
        print(f"  ✗ {name:<22} {type(e).__name__}: {str(e)[:80]}")
        return False


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(JST).strftime("%Y%m%d")
    print(f"日付 {date}   ホスト {socket.gethostname()}")
    try:
        ip = requests.get("https://api.ipify.org", timeout=10).text
        print(f"外から見えるIP {ip}")
    except requests.RequestException:
        pass

    print("\n出走表 info.kyotei.fun ← 学習データと同じ取得元。ここが落ちると予想できない")
    print("  1本目だけでなく連続で叩く（回数で弾かれていないか / 後半Rが載っているか）")
    grid = [(24, 1), (24, 5), (24, 10), (24, 12),
            (7, 10), (20, 10), (22, 10), (12, 10)]
    res = [probe(f"{jcd:02d}場 {rno:>2}R",
                 f"https://info.kyotei.fun/info-{date}-{jcd:02d}-{rno}.html")
           for jcd, rno in grid]
    ok1 = sum(res) >= len(res) // 2
    if any(res) and not all(res):
        print(f"  → {sum(res)}/{len(res)} 成功。全部ではない。"
              "後半Rだけ落ちるなら未掲載、後ろだけ落ちるなら回数制限")

    print("\n公式 boatrace.jp ← 締切時刻・オッズ・直前情報")
    ok2 = probe("締切時刻",
                f"https://www.boatrace.jp/owpc/pc/race/raceindex?jcd=24&hd={date}", 3000)
    probe("オッズ3連単",
          f"https://www.boatrace.jp/owpc/pc/race/odds3t?rno=1&jcd=24&hd={date}", 3000)
    probe("直前情報",
          f"https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=1&jcd=24&hd={date}", 3000)

    print("\n★ここからが本番。『取れるか』ではなく『解析できるか』を見る")
    try:
        import official as OF
        import racecard as RC
    except ImportError as e:
        print(f"  ✗ 読み込めない: {e}  （pip install numpy が要る）")
        return

    print("\n出走表の解析")
    for jcd, rno in ((24, 10), (24, 12), (12, 10), (7, 10)):
        rc = RC.fetch_racecard(date, jcd, rno, tries=1)
        if not rc or len(rc) != 6:
            print(f"  ✗ {jcd:02d}場 {rno:>2}R  6艇そろわない")
            continue
        nz = sum(1 for x in rc if x["n_win"] > 0)
        tj = sum(1 for x in rc if x.get("tenji"))
        print(f"  {'○' if nz == 6 else '✗'} {jcd:02d}場 {rno:>2}R  "
              f"全国勝率 {nz}/6  m_2ren {rc[0]['m_2ren']:.2f} "
              f"b_2ren {rc[0]['b_2ren']:.2f}  "
              f"展示 {tj}/6（展示前なら0で正常）")

    print("\nオッズの解析")
    for jcd, rno in ((24, 10), (24, 12), (12, 10), (7, 10)):
        o = OF.fetch_odds(date, jcd, rno, tries=1)
        if o:
            print(f"  ○ {jcd:02d}場 {rno:>2}R  120点そろった  "
                  f"最小{min(o):.1f} 最大{max(o):.1f}  "
                  f"1/オッズの合計 {sum(1/x for x in o):.3f}（1.337付近なら正しい）")
        else:
            print(f"  ✗ {jcd:02d}場 {rno:>2}R  解析できず（理由は上の行）")

    print("\n今節成績 uchisankaku")
    ok3 = probe("uchisankaku",
                f"https://uchisankaku.sakura.ne.jp/racelist.php?jcode=24&date={date}", 2000)

    print()
    if ok1 and ok2:
        print("→ 主要な取得元には届いている")
    if not ok1:
        print("★ info.kyotei.fun に届いていない。ここが取れないと予想は作れない。")
        print("  Colab では通って Actions で通らないなら、IPで弾かれている。")
        print("  その場合の選択肢:")
        print("   1) しばらく様子を見る（一時的な障害のことがある）")
        print("   2) 出走表を公式(boatrace.jp)から取るように書き換える")
        print("      ★ただし学習データ raw/ は info.kyotei.fun 由来なので、")
        print("        項目の意味がそろっているか確認が要る（v23 の不具合と同じ罠）")
    if not ok3:
        print("★ uchisankaku に届いていない。今節成績（得点率・節内順位）が入らない")


if __name__ == "__main__":
    main()
