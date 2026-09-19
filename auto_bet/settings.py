#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""settings.py -- config.json をメニューで書き換える

金額や上限を変えるのに、JSON を手で開かなくて済むようにするだけのもの。
書く前に config.py の検査を通し、通らない値は保存しない。
覚書（"_" で始まるキー）はそのまま残す。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as config_mod    # noqa: E402

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

YEN, LIMIT_YEN, LIMIT_POINTS, YESNO, MINUTES = "yen", "limit_yen", "limit_pt", "yn", "min"

ITEMS = [
    ("1点あたりの金額", "bet_yen", YEN),
    ("1日の上限", "max_yen_per_day", LIMIT_YEN),
    ("1レースの上限点数", "max_points_per_race", LIMIT_POINTS),
    ("帯（本番）を買う", "buy_obi", YESNO),
    ("穴側（試験）を買う", "buy_ana", YESNO),
    ("締切まで何分前から買うか", "close_min_minutes", MINUTES),
    ("締切まで何分前まで買うか", "close_max_minutes", MINUTES),
    ("ログイン維持の間隔", "keepalive_minutes", MINUTES),
]


def load_raw():
    with open(PATH, encoding="utf-8") as f:
        return json.load(f)


def save_raw(d):
    dirname = os.path.dirname(PATH)
    fd, tmp = tempfile.mkstemp(dir=dirname, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, PATH)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def show(d, key, kind):
    v = d.get(key, config_mod.DEFAULTS.get(key))
    if kind == YESNO:
        return "はい" if v else "いいえ"
    if v is None:
        return "無制限"
    if kind == YEN or kind == LIMIT_YEN:
        return f"{v:,} 円"
    if kind == LIMIT_POINTS:
        return f"{v} 点"
    return f"{v} 分"


def ask(label, kind, now):
    print(f"\n  {label}（いま {now}）")
    if kind == YESNO:
        print("  1=買う / 2=買わない")
    elif kind in (LIMIT_YEN, LIMIT_POINTS):
        print("  数字を入れてください。0 なら無制限")
    elif kind == YEN:
        print("  数字を入れてください（100円単位）")
    else:
        print("  分を入れてください")
    s = input("  新しい値（何も入れずに Enter で変えない）: ").strip()
    if not s:
        return None, "変えませんでした"
    if kind == YESNO:
        if s not in ("1", "2"):
            return None, "1 か 2 を入れてください"
        return s == "1", ""
    try:
        n = float(s) if kind == MINUTES else int(s)
    except ValueError:
        return None, f"数字として読めません: {s}"
    if n < 0:
        return None, "0 以上にしてください"
    if kind in (LIMIT_YEN, LIMIT_POINTS) and n == 0:
        return "__NULL__", ""                  # 0 は「無制限」の意味にする
    if kind == MINUTES and n == int(n):
        n = int(n)
    return n, ""


def main():
    if not os.path.exists(PATH):
        print(f"設定ファイルがありません: {PATH}")
        return 2
    while True:
        try:
            d = load_raw()
        except json.JSONDecodeError as e:
            print(f"config.json が壊れています: {e}")
            return 2
        print("\n   いまの設定")
        print("   " + "-" * 46)
        for i, (label, key, kind) in enumerate(ITEMS, 1):
            print(f"    {i}) {label:<22} {show(d, key, kind)}")
        print("    0) 終わる")
        print("   " + "-" * 46)
        try:
            n = input("   変える番号を入れて Enter: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if n == "0" or not n:
            return 0
        if not n.isdigit() or not (1 <= int(n) <= len(ITEMS)):
            continue

        label, key, kind = ITEMS[int(n) - 1]
        try:
            value, why = ask(label, kind, show(d, key, kind))
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if value is None:
            print(f"  {why}")
            continue
        if value == "__NULL__":
            value = None

        cand = dict(d)
        cand[key] = value
        try:
            config_mod.from_dict(cand)          # 通らない値は保存しない
        except config_mod.ConfigError as e:
            print(f"  ★その値は使えません: {e}")
            continue
        save_raw(cand)
        print(f"  {label} を {show(cand, key, kind)} にしました")


if __name__ == "__main__":
    sys.exit(main())
