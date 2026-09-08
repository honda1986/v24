# -*- coding: utf-8 -*-
"""third.py -- 3着の補正項 h（メモ §35）

  cp(a,b,c) = q(a,b,c) × p1(a)/q1(a) × g(a,b) × h(a,b,c)

  h(a,b,c) = モデルの P(3着=c|1着=a,2着=b) ÷ 市場の同確率

second.py とまったく同じ形。市場を土台にして、ずれだけを学ぶ。
model/lgb_3rd.txt が無ければ h=1 で、2着の補正までの動きに戻る。
"""
import json
import os

import numpy as np

FEATS = ["winner", "second", "lane", "lq3", "q1a", "q2ab", "avg_st",
         "avg_st_vs_oth", "st_setsu", "c_st", "cls_gap", "n_win", "m_2ren",
         "tenji_dev", "mot_pure", "f_count", "jcd", "wave", "wind"]
CAT = ["winner", "second", "lane", "jcd"]


def market_third(q, i1, i2):
    """市場の P(3着=c | 1着=a, 2着=b)。120通りぶんの配列で返す。"""
    den = np.zeros(120)
    for a in range(6):
        for b in range(6):
            if b == a:
                continue
            sel = (i1 == a) & (i2 == b)
            den[sel] = q[sel].sum()
    return q / np.maximum(den, 1e-12)


def build_rows(lanes, meta, q, i1, i2, i3):
    """120通りぶんの特徴量。並びは features.COMBOS と同じ。"""
    def col(k):
        return np.array([x.get(k) if x.get(k) is not None else np.nan
                         for x in lanes], dtype=float)
    ast, sts, cst = col("avg_st"), col("st_setsu"), col("c_st")
    cls, nw, m2 = col("cls_val"), col("n_win"), col("m_2ren")
    tj, mp, fc = col("tenji"), col("mot_pure"), col("f_count")
    with np.errstate(invalid="ignore"):
        td = tj - np.nanmean(tj)
    mk = market_third(q, i1, i2)
    q1 = np.array([q[i1 == a].sum() for a in range(6)])
    out = np.empty((120, len(FEATS)), dtype=np.float32)
    for k in range(120):
        a, b, c = int(i1[k]), int(i2[k]), int(i3[k])
        oth = [x for x in range(6) if x not in (a, b, c)]
        with np.errstate(invalid="ignore"):
            vs = ast[c] - np.nanmean(ast[oth])
        out[k] = [a, b, c, np.log(max(mk[k], 1e-9)), q1[a],
                  q[(i1 == a) & (i2 == b)].sum(),
                  ast[c], vs, sts[c], cst[c], cls[c] - cls[a], nw[c],
                  m2[c], td[c], mp[c], fc[c],
                  meta.get("jcd", np.nan), meta.get("wave", np.nan),
                  meta.get("wind", np.nan)]
    return out, mk


def hvector(model, lanes, meta, q, i1, i2, i3):
    """h を120通りぶん返す。model が None なら全部 1。"""
    if model is None:
        return np.ones(120)
    X, mk = build_rows(lanes, meta, q, i1, i2, i3)
    p = np.asarray(model.predict(X), dtype=float).ravel()
    p = np.maximum(p, 1e-9)
    out = np.ones(120)
    for a in range(6):
        for b in range(6):
            if b == a:
                continue
            sel = (i1 == a) & (i2 == b)
            s = p[sel].sum()
            if s > 0:
                out[sel] = p[sel] / s
    h = np.ones(120)
    ok = mk > 0
    h[ok] = out[ok] / mk[ok]
    # ★極端な値を出させない（second.py と同じ理由）
    return np.clip(h, 0.5, 2.0)


def load(model_dir="model"):
    path = os.path.join(model_dir, "lgb_3rd.txt")
    if not os.path.exists(path):
        return None
    fj = os.path.join(model_dir, "features_3rd.json")
    if os.path.exists(fj):
        with open(fj, encoding="utf-8") as f:
            if json.load(f) != FEATS:
                raise SystemExit("★3着モデルの特徴量が third.py と食い違っています。"
                                 "学習しなおしてください")
    import lightgbm as lgb
    return lgb.Booster(model_file=path)
