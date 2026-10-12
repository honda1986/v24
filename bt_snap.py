#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bt_snap.py -- 判定時オッズでのバックテスト（本番と同じ条件）

bt.py は「確定オッズで選んで、確定オッズで払う」。本番は締切2〜15分前の
オッズで選び、払戻は確定オッズで決まるので、bt.py の回収率は本番では届かない
（本番 9/21〜10/10 で 74.5%、bt.py の帯は 100〜102%）。

ここでは yosou.py が判定のたびに保存したオッズ（odds_snap/、2026-09-26〜）で
本番の判定を再現する:

  1. レースごとに、保存された回を時刻順に見る
  2. その回のオッズで市場確率 q を作り、モデル（1着＋2着・3着の補正）を回す
  3. 帯（select_rule.pick、p/q > PQ_MIN_GH）に入った組が出た**最初の回**で買う
     （本番は買ったら二度と見ないので、それ以降の回は保存されていない）
  4. 払戻は確定した結果（v22 の確定オッズ）

出走表・展示・今節・モーター純度は bt.py と同じ v22 由来（本番は当日に取った値）。
本番の買い目とどれだけ一致するかも出すので、再現の確かさはそこで見ること。

  python bt_snap.py --raw ../v22/raw --tokuten ../v22/tokuten --pure pure.npz \\
      --kfile ../v22/kfile --model model

★データが貯まるほど区間が狭まる。2〜3か月貯まるまでは傾向を見る道具。
★ここの結果を見てしきい値を動かさないこと（band_howto.md §6-4）。
"""
import argparse
import glob
import gzip
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt                       # noqa: E402
import features as F            # noqa: E402
import lightgbm as lgb          # noqa: E402
import second as S              # noqa: E402
import select_rule as SR        # noqa: E402
import third as T               # noqa: E402

BET = 100


def load_snaps(d):
    """(日付, 場, R) -> [(時刻, 締切まで分, オッズ120)]（時刻順）"""
    out = {}
    for path in sorted(glob.glob(f"{d}/*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            js = json.load(f)
        date = int(js["date"])
        for r in js.get("rows") or []:
            od = r.get("odds") or []
            if len(od) == 120 and all(o and o > 0 for o in od):
                out.setdefault((date, r["jcd"], r["rno"]), []).append(
                    (r["t"], r.get("left"), np.asarray(od, float)))
    for v in out.values():
        v.sort(key=lambda z: z[0])
    return out


def live_picks(path, lo, hi):
    """本番で実際に買った組 {(日付, 場, R): set(組)}"""
    try:
        with open(path, encoding="utf-8") as f:
            days = json.load(f).get("days") or []
    except (OSError, ValueError):
        return {}
    out = {}
    for d in days:
        if not (lo <= int(d["date"]) <= hi):
            continue
        for p in d.get("picks") or []:
            out[(int(d["date"]), p["jcd"], p["rno"])] = {b["combo"] for b in p["buys"]}
    return out


class Model:
    def __init__(self, mdir):
        self.m1 = lgb.Booster(model_file=f"{mdir}/lgb_mf.txt")
        self.feats = json.load(open(f"{mdir}/features.json", encoding="utf-8"))
        self.m2, self.m3 = S.load(mdir), T.load(mdir)
        if self.m2 is None or self.m3 is None:
            raise SystemExit("2着・3着の補正モデルが読めません（本番と同じ条件にならない）")

    def predict(self, lanes, mt, odds):
        """このオッズのときの (q, 3連単の p)"""
        q, q1 = F.market_probs(odds)
        raw = np.asarray(self.m1.predict(F.build_race(lanes, mt, q1, feats=self.feats)), float)
        cp = F.trifecta(raw / raw.sum(), q)
        cp = (cp * S.gmatrix(self.m2, lanes, mt, q, F.FIRST, bt.SEC_IDX)[F.FIRST, bt.SEC_IDX]
              * T.hvector(self.m3, lanes, mt, q, F.FIRST, bt.SEC_IDX, bt.THI_IDX))
        return q, cp / cp.sum()


def summary(lab, rows, out=print):
    """rows: [(日付, 払戻, 判定時オッズ, q, 的中)]（1点100円）"""
    if not rows:
        out(f"  {lab}: 買い目なし")
        return
    a = np.array([r[:4] for r in rows], float)
    hit = np.array([r[4] for r in rows], bool)
    d, pay, od, q = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
    roi = pay.sum() / (BET * len(a))
    ud = np.unique(d)
    g = {u: np.where(d == u)[0] for u in ud}
    rng = np.random.default_rng(0)
    bs = []
    for _ in range(2000):
        ix = np.concatenate([g[u] for u in rng.choice(ud, len(ud))])
        bs.append(pay[ix].sum() / (BET * len(ix)))
    bs = np.array(bs)
    out(f"  {lab}: {len(a)}点 {len(np.unique(d))}日  的中 {hit.sum()}本 ({hit.mean()*100:.1f}%)  "
        f"回収率 {roi*100:5.1f}%  95%区間 [{np.percentile(bs,2.5)*100:.0f}, "
        f"{np.percentile(bs,97.5)*100:.0f}]  P(>100%) {np.mean(bs > 1):.2f}")
    out(f"      判定時オッズで払われていたら {np.where(hit, od*BET, 0).sum()/(BET*len(a))*100:.1f}%"
        f"   実測/市場 {hit.sum()/q.sum():.3f}（トントンは 1.337）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="../v22/raw")
    ap.add_argument("--tokuten", default="../v22/tokuten")
    ap.add_argument("--pure", default="pure.npz")
    ap.add_argument("--kfile", default="../v22/kfile")
    ap.add_argument("--model", default="model")
    ap.add_argument("--snap", default="odds_snap")
    ap.add_argument("--history", default="history.json")
    args = ap.parse_args()

    snaps = load_snaps(args.snap)
    if not snaps:
        raise SystemExit(f"{args.snap}/ に判定時オッズがありません")
    lo, hi = min(k[0] for k in snaps), max(k[0] for k in snaps)
    print(f"判定時オッズ {lo}〜{hi}  {len(snaps):,}レース "
          f"{sum(len(v) for v in snaps.values()):,}回", flush=True)

    # 出走表などは bt.py と同じ。足切り(淡水)は本番と同じく後で掛ける
    ca = argparse.Namespace(raw=args.raw, tokuten=args.tokuten, pure=args.pure,
                            kfile=args.kfile, frm=lo, to=hi)
    band_ok = SR.band_ok
    SR.band_ok = lambda j, w, v: True
    races = bt.collect(ca)
    SR.band_ok = band_ok
    M = Model(args.model)

    A, B, ANA = [], [], []          # 判定時オッズ / 確定オッズ / 穴側(判定時)
    per_left = {}                   # 各回を独立に判定したとき（診断）
    mine = {}
    nr = 0
    for (d, lanes, mt, od_f, q_f, q1_f, hit) in races:
        key = (d, mt["jcd"], mt["rno"])
        if key not in snaps or not SR.band_ok(mt["jcd"], mt["wave"], mt["wind"]):
            continue
        nr += 1
        pay_of = lambda i: float(od_f[i]) * BET if i == hit else 0.0
        # --- 本番の再現：最初に帯が出た回で買う ---
        bought = ana_done = False
        for t, left, od in snaps[key]:
            q, cp = M.predict(lanes, mt, od)
            buy = SR.pick(q, cp, SR.PQ_MIN_GH)
            for i in buy:                                    # 診断：各回を独立に
                per_left.setdefault(left, []).append((d, pay_of(i), od[i], q[i], i == hit))
            if buy and not bought:
                bought = True
                mine[key] = {F.COMBOS[i] for i in buy}
                A += [(d, pay_of(i), od[i], q[i], i == hit) for i in buy]
            if not ana_done and SR.ana_ok(mt["jcd"], mt["wave"], mt["wind"]):
                ab = [i for i in SR.pick_ana(q, cp, list(od)) if i not in set(buy)]
                if ab:
                    ana_done = True
                    ANA += [(d, pay_of(i), od[i], q[i], i == hit) for i in ab]
        # --- 従来のバックテスト：確定オッズで選ぶ（同じレースで） ---
        q, cp = M.predict(lanes, mt, od_f)
        B += [(d, pay_of(i), od_f[i], q[i], i == hit) for i in SR.pick(q, cp, SR.PQ_MIN_GH)]

    print(f"\n照合できたレース {nr:,}（淡水を除く）  帯 p/q > {SR.PQ_MIN_GH}")
    print("\n【判定時オッズで選ぶ＝本番と同じ条件】")
    summary("帯", A)
    print("\n【確定オッズで選ぶ＝従来の bt.py と同じ条件（同じレース）】")
    summary("帯", B)
    print("\n【穴側（判定時オッズ、記録のみのルール）】")
    summary("穴側", ANA)

    live = live_picks(args.history, lo, hi)
    if live:
        ks = set(live) | set(mine)
        both = sum(1 for k in ks if k in live and k in mine)
        same = sum(1 for k in ks if live.get(k) == mine.get(k))
        print(f"\n本番の買い目との一致: 本番 {len(live)}レース / 再現 {len(mine)}レース / "
              f"両方 {both} / 組まで同じ {same}")
        print("  ※ずれは出走表・展示の取得元の違い（本番は当日取得、ここは v22）と、"
              "本番が取りこぼした回（データ欠など）から来る")

    print("\n【診断】各回を独立に判定した場合、締切まで何分の回か（同じ組を何度も数える）")
    for lo_, hi_ in ((2, 4), (5, 7), (8, 10), (11, 15)):
        rows = [r for k, v in per_left.items() if k is not None and lo_ <= k <= hi_ for r in v]
        summary(f"締切{lo_:>2}〜{hi_:>2}分前", rows)
    print("  ※本番は買ったら次の回を保存しないので、遅い回ほど「早く買えなかったレース」に偏る")


if __name__ == "__main__":
    main()
