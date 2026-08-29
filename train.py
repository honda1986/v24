#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train.py -- MFモデル(市場+ファンダ)を学習する。Colab で動かす想定。

■ v23 との違い
  ・モデルは1本だけ。p2/p3 のカスケードは作らない
    (1着だけモデル化して2着3着は市場の条件付き構造を借りる。引き継ぎメモ §7-1c)
  ・オッズが特徴量に入る。だから学習にもオッズが要る

■ 使い方 (Colab)
    !pip -q install lightgbm
    !rm -rf v22 v24 && git clone --depth 1 https://github.com/honda1986/v22.git
    !git clone --depth 1 https://github.com/honda1986/v24.git
    !python v24/pure.py --kfile v22/kfile --out /content/pure.npz
    !python v24/train.py --raw v22/raw --tokuten v22/tokuten --pure /content/pure.npz \
                         --out v24/model --cut 20250316

■ 検証の作法(メモ §3)
  ・--cut より前だけで学習する。それ以降は一切使わない
  ・特徴量を足すときは features.py だけを直す。ここは触らない
"""
import argparse
import glob
import gzip
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F


def load_days(raw_dir, tok_dir, pure_path):
    p = np.load(pure_path, allow_pickle=True)
    pk = p["date"].astype(np.int64) * 100000 + p["toban"]
    po = np.argsort(pk)
    pk, pv = pk[po], p["vals"][po][:, list(p["cols"]).index("mot_pure")]

    tokf = {os.path.basename(x)[:8]: x for x in glob.glob(f"{tok_dir}/*.json.gz")}
    rawf = sorted(glob.glob(f"{raw_dir}/*.json.gz"))
    print(f"raw {len(rawf)}日 / tokuten {len(tokf)}日")
    X, Y, D = [], [], []
    t0 = time.time()
    for k, path in enumerate(rawf):
        d = os.path.basename(path)[:8]
        with gzip.open(path, "rt", encoding="utf-8") as f:
            rd = json.load(f)
        tk, meta = {}, {}
        if d in tokf:
            with gzip.open(tokf[d], "rt", encoding="utf-8") as f:
                td = json.load(f)
            for js, v in (td.get("venues") or {}).items():
                j = int(js)
                for r in v.get("races", []):
                    meta[(j, r["rno"])] = (r.get("name", ""), v.get("day_no"),
                                           v.get("n_days"))
                    for x in r["lanes"]:
                        tk[(j, r["rno"], x["lane"])] = x
        for r in rd["races"]:
            if "error" in r or not r.get("hit") or len(r.get("entries", [])) != 6:
                continue
            od = r.get("odds") or []
            if len(od) != 120 or not all(o and o > 0 for o in od):
                continue
            try:
                a = int(r["hit"].split("-")[0])
            except (ValueError, IndexError):
                continue
            q, q1 = F.market_probs(od)
            if q is None:
                continue
            nm, day_no, n_days = meta.get((r["jcd"], r["rno"]), ("", None, None))
            lanes = []
            ok = True
            for e in sorted(r["entries"], key=lambda z: z["lane"]):
                x = tk.get((r["jcd"], r["rno"], e["lane"]), {})
                tb = x.get("toban")
                mp = np.nan
                if tb:
                    key = int(d) * 100000 + int(tb)
                    i = np.searchsorted(pk, key)
                    if i < len(pk) and pk[i] == key:
                        mp = float(pv[i])
                tj = e.get("tenji")
                lanes.append({
                    "lane": e["lane"], "cls_val": e.get("cls_val"),
                    "age": e.get("age"), "weight": e.get("weight"),
                    "f_count": e.get("f_count"), "avg_st": e.get("avg_st"),
                    "n_win": e.get("n_win"), "n_2ren": e.get("n_2ren"),
                    "l_win": e.get("l_win"), "l_2ren": e.get("l_2ren"),
                    "m_2ren": e.get("m_2ren"), "b_2ren": e.get("b_2ren"),
                    "tok": x.get("tokuten"), "srank": x.get("rank"),
                    "genten": x.get("genten"), "nruns": x.get("n_runs"),
                    "st_setsu": x.get("st_setsu"), "c_win": x.get("c_win"),
                    "c_ren3": x.get("c_ren3"), "c_st": x.get("c_st"),
                    "tenji": tj if tj and tj > 0 else None,
                    "mot_pure": None if np.isnan(mp) else mp,
                })
            if not ok:
                continue
            mt = {"jcd": r["jcd"], "rno": r["rno"], "day_no": day_no,
                  "n_days": n_days,
                  "is_final": 1 if any(w in (nm or "")
                                       for w in ("準優", "優勝", "選抜")) else 0}
            X.append(F.build_race(lanes, mt, q1))
            y = np.zeros(6, np.int8); y[a - 1] = 1
            Y.append(y); D.append(int(d))
        if (k + 1) % 200 == 0:
            print(f"  {k+1}/{len(rawf)}日  {len(X):,}レース  "
                  f"{time.time()-t0:.0f}秒", flush=True)
    return (np.stack(X).astype(np.float32), np.stack(Y),
            np.array(D, dtype=np.int32))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="v22/raw")
    ap.add_argument("--tokuten", default="v22/tokuten")
    ap.add_argument("--pure", default="pure.npz")
    ap.add_argument("--out", default="model")
    ap.add_argument("--cut", type=int, default=20250316,
                    help="この日より前だけで学習する")
    args = ap.parse_args()
    import lightgbm as lgb

    X, Y, D = load_days(args.raw, args.tokuten, args.pure)
    n = len(D)
    print(f"\n読み込み {n:,}レース × 6艇 × {X.shape[2]}特徴量")
    tr = D < args.cut
    days = np.sort(np.unique(D[tr]))
    iv_cut = days[int(len(days) * 0.90)]
    m_tr, m_iv = tr & (D < iv_cut), tr & (D >= iv_cut)
    print(f"学習 {int(m_tr.sum()):,}レース (〜{iv_cut}) / "
          f"内側検証 {int(m_iv.sum()):,}レース / "
          f"以降 {int((~tr).sum()):,}レースは一切使わない")

    Xf = X.reshape(n * 6, -1)
    Yf = Y.reshape(n * 6)
    cat = [F.FEATS.index(c) for c in F.CAT]
    params = dict(objective="binary", learning_rate=0.04, num_leaves=63,
                  min_data_in_leaf=200, feature_fraction=0.8,
                  bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=42)
    m = lgb.train(params,
                  lgb.Dataset(Xf[np.repeat(m_tr, 6)], Yf[np.repeat(m_tr, 6)],
                              feature_name=F.FEATS, categorical_feature=cat),
                  num_boost_round=3000,
                  valid_sets=[lgb.Dataset(Xf[np.repeat(m_iv, 6)],
                                          Yf[np.repeat(m_iv, 6)],
                                          feature_name=F.FEATS,
                                          categorical_feature=cat)],
                  callbacks=[lgb.early_stopping(100, verbose=False)])
    print(f"木の数 {m.best_iteration}")

    def race_ll(mask):
        idx = np.where(mask)[0]
        p = m.predict(X[idx].reshape(-1, X.shape[2])).reshape(len(idx), 6)
        p = p / p.sum(1, keepdims=True)
        return float(-np.log(np.clip(p[Y[idx] == 1], 1e-12, None)).mean())

    def market_ll(mask):
        idx = np.where(mask)[0]
        lq = X[idx][:, :, F.FEATS.index("lq")]
        q = np.exp(lq); q = q / q.sum(1, keepdims=True)
        return float(-np.log(np.clip(q[Y[idx] == 1], 1e-12, None)).mean())

    print("\n=== 1着の対数損失 ===")
    for nm, mask in (("内側検証", m_iv), ("学習に使っていない期間", ~tr)):
        if mask.sum() < 100:
            continue
        a, b = market_ll(mask), race_ll(mask)
        print(f"  {nm:<22} 市場 {a:.4f} → モデル {b:.4f}  ({b-a:+.4f})")
    print("  ★ 市場を下回っていること。上回っていたら投入しない")

    os.makedirs(args.out, exist_ok=True)
    m.save_model(f"{args.out}/lgb_mf.txt")
    with open(f"{args.out}/features.json", "w", encoding="utf-8") as f:
        json.dump(F.FEATS, f, ensure_ascii=False)
    imp = sorted(zip(F.FEATS, m.feature_importance("gain")),
                 key=lambda z: -z[1])[:12]
    print(f"\n{args.out}/ に保存しました")
    print("効いた特徴量 上位12:")
    for k, v in imp:
        print(f"  {k:<16}{v:>14,.0f}")


if __name__ == "__main__":
    main()
