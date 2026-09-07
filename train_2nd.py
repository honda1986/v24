#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_2nd.py -- 2着の補正 g を学習する（メモ §30）

  python train_2nd.py --raw v22/raw --tokuten v22/tokuten \
      --pure /content/pure.npz --out model --cut 20250316

出るもの: model/lgb_2nd.txt と model/features_2nd.json

★学習するのは「市場の条件付き確率からのずれ」。市場の値を対数で特徴量に入れて
  あるので、モデルはそこからの差分だけを学べばよい。学習が失敗しても
  g≈1 に落ちるだけで、市場より悪くはなりにくい。
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
import features as F          # noqa: E402
import second as S            # noqa: E402


def load_rows(raw_dir, tok_dir, pure_path):
    p = np.load(pure_path, allow_pickle=True)
    cols = list(p["cols"])
    pk = p["date"].astype(np.int64) * 100000 + p["toban"]
    po = np.argsort(pk); pk = pk[po]
    pv = p["vals"][po][:, cols.index("mot_pure")]
    tokf = {os.path.basename(x)[:8]: x for x in glob.glob(f"{tok_dir}/*.json.gz")}
    rawf = sorted(glob.glob(f"{raw_dir}/*.json.gz"))
    print(f"raw {len(rawf)}日 / tokuten {len(tokf)}日")
    X, Y, D = [], [], []
    t0 = time.time()
    for k, path in enumerate(rawf):
        d = os.path.basename(path)[:8]
        with gzip.open(path, "rt", encoding="utf-8") as f:
            rd = json.load(f)
        tk = {}
        if d in tokf:
            with gzip.open(tokf[d], "rt", encoding="utf-8") as f:
                td = json.load(f)
            for js, v in (td.get("venues") or {}).items():
                for r in v.get("races", []):
                    for x in r["lanes"]:
                        tk[(int(js), r["rno"], x["lane"])] = x
        for r in rd["races"]:
            if "error" in r or not r.get("hit") or len(r.get("entries", [])) != 6:
                continue
            od = r.get("odds") or []
            if len(od) != 120 or not all(o and o > 0 for o in od):
                continue
            try:
                a, b = (int(v) - 1 for v in r["hit"].split("-")[:2])
            except (ValueError, IndexError):
                continue
            q, _ = F.market_probs(od)
            if q is None:
                continue
            lanes = []
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
                    "cls_val": e.get("cls_val"), "f_count": e.get("f_count"),
                    "avg_st": e.get("avg_st"), "n_win": e.get("n_win"),
                    "m_2ren": e.get("m_2ren"),
                    "st_setsu": x.get("st_setsu"), "c_st": x.get("c_st"),
                    "tenji": tj if tj and tj > 0 else None,
                    "mot_pure": None if np.isnan(mp) else mp})
            w = (r.get("weather") or {})
            meta = {"jcd": r["jcd"], "wave": w.get("wave"), "wind": w.get("wind")}
            rows, _ = S.build_rows(lanes, meta, q, F.FIRST, SECOND)
            # ★実際に1着だった a の行だけを使う。これが条件付き確率の定義。
            for j, (aa, bb) in enumerate(S.PAIRS):
                if aa != a:
                    continue
                X.append(rows[j]); Y.append(1 if bb == b else 0); D.append(int(d))
        if (k + 1) % 200 == 0:
            print(f"  {k+1}/{len(rawf)}日  {len(X):,}行  {time.time()-t0:.0f}秒",
                  flush=True)
    return np.array(X, np.float32), np.array(Y, np.int8), np.array(D, np.int32)


SECOND = np.array([int(c[2]) - 1 for c in F.COMBOS])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="v22/raw")
    ap.add_argument("--tokuten", default="v22/tokuten")
    ap.add_argument("--pure", default="pure.npz")
    ap.add_argument("--out", default="model")
    ap.add_argument("--cut", type=int, default=20250316)
    args = ap.parse_args()
    import lightgbm as lgb

    X, Y, D = load_rows(args.raw, args.tokuten, args.pure)
    print(f"\n読み込み {len(X):,}行 × {X.shape[1]}特徴量")
    tr = D < args.cut
    days = np.sort(np.unique(D[tr])); iv = days[int(len(days) * 0.90)]
    m_tr, m_iv = tr & (D < iv), tr & (D >= iv)
    print(f"学習 {int(m_tr.sum()):,} / 内側検証 {int(m_iv.sum()):,} / "
          f"以降 {int((~tr).sum()):,} は使わない")
    cat = [S.FEATS.index(c) for c in S.CAT]
    params = dict(objective="binary", learning_rate=0.05, num_leaves=31,
                  min_data_in_leaf=500, feature_fraction=0.8,
                  bagging_fraction=0.8, bagging_freq=1, lambda_l2=2.0,
                  verbose=-1, seed=42)
    m = lgb.train(params,
                  lgb.Dataset(X[m_tr], Y[m_tr], feature_name=S.FEATS,
                              categorical_feature=cat),
                  num_boost_round=2000,
                  valid_sets=[lgb.Dataset(X[m_iv], Y[m_iv], feature_name=S.FEATS,
                                          categorical_feature=cat)],
                  callbacks=[lgb.early_stopping(100, verbose=False)])
    print(f"木の数 {m.best_iteration}")

    def ll(p, y):
        p = np.clip(p, 1e-9, 1 - 1e-9)
        return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())

    print("\n=== 2着の対数損失（1着で条件づけ・5候補）===")
    for nm, mask in (("内側検証", m_iv), ("学習に使っていない期間", ~tr)):
        if mask.sum() < 100:
            continue
        qm = np.exp(X[mask][:, S.FEATS.index("lq2")])
        pm = m.predict(X[mask])
        print(f"  {nm:<22} 市場 {ll(qm, Y[mask]):.5f} → "
              f"モデル {ll(pm, Y[mask]):.5f}  ({ll(pm, Y[mask])-ll(qm, Y[mask]):+.5f})")
    print("  ★市場を下回っていること。上回っていたら使わない")

    os.makedirs(args.out, exist_ok=True)
    m.save_model(f"{args.out}/lgb_2nd.txt")
    with open(f"{args.out}/features_2nd.json", "w", encoding="utf-8") as f:
        json.dump(S.FEATS, f, ensure_ascii=False)
    print(f"\n{args.out}/lgb_2nd.txt に保存しました")
    imp = sorted(zip(S.FEATS, m.feature_importance("gain")), key=lambda z: -z[1])[:10]
    for k, v in imp:
        print(f"  {k:<16}{v:>14,.0f}")


if __name__ == "__main__":
    main()
