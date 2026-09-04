#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_history.py -- history.json を「JSONとして」統合する

★なぜ必要か（2026-09-04）
  history.json は yosou / settle(motor.yml) / prefetch が別々に書く。
  中身は1行の大きなJSONなので、git から見ると常に「同じ行の衝突」になる。
  rebase では直せない。-X theirs で片方を丸ごと採ると、
  もう片方の書き込み（settle が入れた的中・払戻）が黙って消える。

  なので git に混ぜさせるのをやめた。リモートの最新を取り直し、
  そこに自分の書いたぶんを「意味を見て」足す。衝突は起きようがない。

  python merge_history.py 自分の.json 出力先.json
"""
import json
import re
import sys


def load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def key(x):
    return (x.get("jcd"), x.get("rno"))


def merge_list(base, mine, prefer_settled):
    """(jcd,rno) で突き合わせて統合。base はリモート、mine は自分。"""
    out = {key(x): x for x in base or []}
    for x in mine or []:
        k = key(x)
        cur = out.get(k)
        if cur is None:
            out[k] = x
            continue
        if prefer_settled:
            # ★結果(hit)が入っているほうを優先する。settle の仕事を消さない。
            #   両方に入っていなければ、内訳の多い自分のほうを採る。
            if cur.get("hit") is not None and x.get("hit") is None:
                continue
            if x.get("hit") is not None and cur.get("hit") is None:
                out[k] = x
                continue
            # 結果の有無が同じなら、あとから書いた自分を採るが、
            # リモートにしかない項目は落とさない
            merged = dict(cur)
            merged.update({a: b for a, b in x.items() if b is not None})
            out[k] = merged
        else:
            out[k] = x
    return list(out.values())


def merge_day(base, mine):
    d = dict(base)
    d["picks"] = merge_list(base.get("picks"), mine.get("picks"), True)
    d["races"] = merge_list(base.get("races"), mine.get("races"), False)
    sk = dict(base.get("skipped") or {})
    for k, v in (mine.get("skipped") or {}).items():
        # どちらもその日の累計。大きいほうが新しい
        sk[k] = max(sk.get(k, 0), v)
    d["skipped"] = sk
    d["runs"] = max(base.get("runs", 0), mine.get("runs", 0))
    # ★"—"(未実行の印)を混ぜて max を取ると、記号のほうが大きく判定されて
    #   時刻が消える。実際に踏んだので、時刻の形のものだけ比べる。
    lr = [x for x in (base.get("last_run"), mine.get("last_run"))
          if isinstance(x, str) and re.fullmatch(r"\d{1,2}:\d{2}", x)]
    if lr:
        d["last_run"] = max(lr, key=lambda t: [int(v) for v in t.split(":")])
    return d


def main():
    if len(sys.argv) != 3:
        sys.exit("使い方: merge_history.py 自分の.json 出力先.json")
    mine, out = load(sys.argv[1]), load(sys.argv[2])
    days = {d["date"]: d for d in (out.get("days") or [])}
    added = merged = 0
    for d in mine.get("days") or []:
        if d["date"] in days:
            days[d["date"]] = merge_day(days[d["date"]], d)
            merged += 1
        else:
            days[d["date"]] = d
            added += 1
    out["days"] = sorted(days.values(), key=lambda d: d["date"])
    up = [x for x in (mine.get("updated"), out.get("updated")) if x]
    if up:
        out["updated"] = max(up)
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    tot = sum(len(d.get("picks") or []) for d in out["days"])
    print(f"  history.json 統合: {merged}日を突き合わせ / {added}日を追加 / "
          f"買い目 {tot}レース")


if __name__ == "__main__":
    main()
