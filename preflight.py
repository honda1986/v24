#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preflight.py -- 本番に金を入れる前の関門を、全部その場で実行して判定する

★「たぶん大丈夫」を潰すためのもの。説明ではなく測定で答える。

  python preflight.py --kfile ../v22/kfile
  python preflight.py --kfile ../v22/kfile --ntfy 自分のトピック名

判定するもの
  1. モデルと特徴量の整合          selftest 相当
  2. モーター純度が新しいか
  3. 出走表が解析できるか          実ページで6艇そろうか
  4. オッズの数値が正しいか        120点 / 1/オッズ合計 ≈ 1.337
  5. ★オッズの並び順が正しいか     過去の払戻金と突き合わせる
  6. 通知が実際に飛ぶか            ntfy にテスト送信
  7. 気象の足切りが動くか
"""
import argparse
import datetime
import gzip
import json
import os
import sys

JST = datetime.timezone(datetime.timedelta(hours=9))
R = []          # (通ったか, 名前, 補足)


def gate(name, ok, note=""):
    R.append((ok, name, note))
    print(f"  {'○' if ok else '✗'} {name}  {note}", flush=True)
    return ok


def g1_model():
    try:
        import features as F
        feats = json.load(open("model/features.json", encoding="utf-8"))
    except (OSError, ValueError) as e:
        return gate("モデルと特徴量", False, f"読めない: {e}")
    if feats != F.FEATS:
        return gate("モデルと特徴量", False,
                    f"食い違い モデル{len(feats)} / いま{len(F.FEATS)}")
    if not os.path.isfile("model/lgb_mf.txt"):
        return gate("モデルと特徴量", False, "lgb_mf.txt が無い")
    return gate("モデルと特徴量", True, f"{len(feats)}個で一致")


def g2_motor(today):
    j = None
    try:
        j = json.load(open("motor/latest.json", encoding="utf-8"))
    except (OSError, ValueError):
        return gate("モーター純度", False, "motor/latest.json が無い")
    d = str(j.get("date") or "")
    n = len((j.get("values") or {}))
    if not d or n < 500:
        return gate("モーター純度", False, f"中身が薄い（{d} {n}人）")
    age = (datetime.date(int(today[:4]), int(today[4:6]), int(today[6:8]))
           - datetime.date(int(d[:4]), int(d[4:6]), int(d[6:8]))).days
    return gate("モーター純度", age <= 3, f"{d} {n:,}人（{age}日前）")


def kf_races(kdir, days=4, per_day=8):
    """★開催を確認してからテストする。

    今日の場を決め打ちすると、開催していない場を叩いて「解析できない」と
    出る（実測で踏んだ）。Kファイルに結果が載っている＝確実に開催した
    レースを使う。出走表もオッズも過去日のページが残っている。

    戻り値: (代表の日付, [(日付, jcd, rno, hit, pay, 異常があったか), ...])
    ★日付は行ごとに持たせる。複数日から集めるのに日付を1つしか返さないと、
      別の日のレースを違う日付で照会することになる。
    """
    import glob
    out, date = [], None
    for p in sorted(glob.glob(f"{kdir}/*.json.gz"), reverse=True)[:days]:
        d = os.path.basename(p)[:8]
        with gzip.open(p, "rt", encoding="utf-8") as f:
            rs = json.load(f).get("races") or []
        rows = []
        for r in rs:
            es = r.get("entries") or []
            if not r.get("hit") or not (r.get("pay_3t") or 0):
                continue
            # 欠場・失格・転覆があると「払戻＝確定オッズ×100」が崩れうる
            odd = any(not str(e.get("chaku") or "").isdigit() for e in es)
            rows.append((d, r["jcd"], r["rno"], r["hit"], float(r["pay_3t"]), odd))
        if not rows:
            continue
        date = date or d
        step = max(1, len(rows) // per_day)
        out.extend(rows[::step][:per_day])
    return date, out


def g3_racecard(races):
    import racecard as RC
    ok = bad = 0
    for d, jcd, rno in races:
        rc = RC.fetch_racecard(d, jcd, rno, tries=2)
        if rc and len(rc) == 6:      # 既定値ページは racecard 側で弾く
            ok += 1
        else:
            bad += 1
    return gate("出走表の解析", ok >= 2, f"{ok}成功 / {bad}失敗")


def g4_odds(races):
    import official as OF
    sums, ok = [], 0
    for d, jcd, rno in races:
        o = OF.fetch_odds(d, jcd, rno, tries=2, verbose=False)
        if o and len(o) == 120 and min(o) >= 1.0:
            s = sum(1 / x for x in o)
            sums.append(s)
            ok += 1 if 1.30 <= s <= 1.37 else 0
    if not sums:
        return gate("オッズの数値", False, "1件も解析できない")
    return gate("オッズの数値", ok >= 2,
                f"{ok}/{len(sums)}件が正常  1/オッズ合計 "
                + " ".join(f"{s:.3f}" for s in sums[:4]))


def g5_order(rows):
    """★最重要。並び順が違うと、静かに間違った組を買い続ける。

    払戻金 = 確定オッズ × 100 で検算する。
    ★並び順が狂っていれば「全部」外れる。一部だけ外れるのは別の原因なので、
      欠場・失格の有無で分けて数える（返還があると払戻とオッズの関係が崩れる）。
    """
    import official as OF
    from features import COMBOS, CIX
    ok = miss = 0
    ng_normal, ng_odd, detail = [], [], []
    for d, jcd, rno, hit, pay, odd in rows:
        if hit not in CIX:
            continue
        o = OF.fetch_odds(d, jcd, rno, tries=2, verbose=False)
        if not o:
            miss += 1
            continue
        got = o[CIX[hit]] * 100.0
        if abs(got - pay) / pay <= 0.02:
            ok += 1
            continue
        (ng_odd if odd else ng_normal).append((jcd, rno))
        cand = [COMBOS[k] for k, v in enumerate(o)
                if abs(v * 100 - pay) / pay <= 0.02]
        detail.append(f"{d} {jcd:02d}場{rno}R {hit} 払戻{pay:,.0f} "
                      f"→ オッズは{got:,.0f}  合う組{cand[:2]}  "
                      f"{'欠場/失格あり' if odd else '★正常なレース'}")
    n = ok + len(ng_normal) + len(ng_odd)
    if n == 0:
        return gate("★オッズの並び順", False, f"検算できず（取れず{miss}件）")
    # 正常なレースで1件でも外れたら並び順を疑う。
    # 欠場・失格のあるレースは返還で払戻が変わるので、外れても並び順の証拠にならない。
    good = not ng_normal and ok >= 8
    gate("★オッズの並び順",
         good,
         f"一致{ok} / 不一致{len(ng_normal)+len(ng_odd)}"
         f"（うち欠場・失格{len(ng_odd)}）/ 取れず{miss}")
    for d in detail[:6]:
        print(f"      {d}")
    if ng_normal:
        print("      ★正常なレースで外れている。並び順を疑うこと")
    return good


def g6_ntfy(topic):
    if not topic:
        return gate("通知(ntfy)", False, "トピック未指定。--ntfy で指定して確かめること")
    import requests
    try:
        r = requests.post("https://ntfy.sh",
                          json={"topic": topic, "title": "v24 テスト送信",
                                "message": "これが届けば通知経路は生きています",
                                "priority": 3, "tags": ["white_check_mark"]},
                          timeout=15)
        return gate("通知(ntfy)", r.status_code < 300,
                    f"HTTP {r.status_code}  スマホに届いたか確認すること")
    except requests.RequestException as e:
        return gate("通知(ntfy)", False, type(e).__name__)


def g7_rule():
    import select_rule as SR
    cases = [((24, 1, 2), True), ((2, 1, 2), False), ((24, 6, 2), False),
             ((24, 1, 5), False), ((24, None, 2), False)]
    bad = [c for c, want in cases if SR.race_ok(*c) is not want]
    return gate("気象の足切り", not bad, f"5例すべて期待どおり" if not bad else f"{bad}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kfile", default="../v22/kfile")
    ap.add_argument("--ntfy", default=os.environ.get("NTFY_TOPIC", ""))
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--per-day", type=int, default=6)
    args = ap.parse_args()
    kdate, rows = kf_races(args.kfile, args.days, args.per_day)
    if not kdate:
        print(f"★ {args.kfile} にKファイルがありません")
        return 1
    races = [(d, j, r) for d, j, r, *_ in rows[:4]]
    print(f"検査に使う日: {sorted({r[0] for r in rows})}"
          f"（開催が確認できたレース {len(rows)}件、"
          f"うち欠場・失格あり {sum(1 for r in rows if r[5])}件）")

    print(f"=== preflight ===\n")
    # ★1つが例外で落ちても後ろまで進める。前回は g4 の例外で、一番見たかった
    #   「並び順」と「通知」に到達できなかった。
    today = datetime.datetime.now(JST).strftime("%Y%m%d")
    for fn, a in ((g1_model, ()), (g2_motor, (today,)),
                  (g3_racecard, (races,)), (g4_odds, (races,)),
                  (g5_order, (rows,)),
                  (g6_ntfy, (args.ntfy,)), (g7_rule, ())):
        try:
            fn(*a)
        except Exception as e:                       # noqa: BLE001
            import traceback
            gate(fn.__name__, False, f"例外 {type(e).__name__}: {e}")
            traceback.print_exc()

    ng = [n for ok, n, _ in R if not ok]
    print(f"\n=== {len(R) - len(ng)}/{len(R)} 通過 ===")
    if not ng:
        print("すべて通りました。ここまでは測定で確認された状態です。")
        print("★それでも、実運用の回収率が 95.3% に乗るかは別問題。")
        print("  バックテストは確定オッズ。実際は締切までにオッズが動く。")
        print("  2週間は買わずに記録だけ取ること。")
        return 0
    print("通っていない関門:")
    for n in ng:
        print(f"  ・{n}")
    print("\n★ひとつでも欠けているうちは金を入れないこと。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
