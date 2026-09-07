# -*- coding: utf-8 -*-
"""second.py -- 2着の補正項 g

★なぜ必要か（2026-09-04、メモ §30）
  v24 の3連単は cp = q × p1/q1 で、2着3着の並びを市場から丸ごと借りている。
  そのため「市場の2着の値付けの歪み」は、そのまま買い目に入ってしまう。
  特徴量をいくら足しても直らない。構造の問題だった。

  実測された歪み：1着=1号艇のとき、
    ・3号艇のSTが2号艇より速く見える → 市場は 1-3-x を買いすぎ（実測/市場 1.020）
    ・3号艇のSTが遅く見える         → 市場は 1-3-x を買わなすぎ（同 1.204）
  3号艇の武器はまくり。1号艇が勝った＝まくり不発、なので
  「攻めそうな3号艇」ほど2着に残らない。市場はこの条件付けができていない。

★設計の考え方（1着とまったく同じ）
  市場を土台にして、そこからのずれだけを学ぶ。

      cp(a,b,c) = q(a,b,c) × p1(a)/q1(a) × g(a,b)

      g(a,b) = モデルの P(2着=b|1着=a) ÷ 市場の P(2着=b|1着=a)

  g=1 なら今までと完全に同じ挙動に戻る。モデルが無ければ 1 を返す。
  ★この「土台＋ずれ」の形にしておくと、学習が失敗しても市場より悪くならない。
"""
import json
import os

import numpy as np

# 学習と本番で必ず同じ並び。ここを直したら学習しなおすこと。
FEATS = ["winner", "lane", "lq2", "q1a", "avg_st", "avg_st_vs1", "avg_st_vs_oth",
         "st_setsu", "c_st", "cls_gap", "n_win", "m_2ren", "tenji_dev",
         "mot_pure", "f_count", "jcd", "wave", "wind"]
CAT = ["winner", "lane", "jcd"]
PAIRS = [(a, b) for a in range(6) for b in range(6) if b != a]


def market_second(q, first_idx, second_idx):
    """市場の条件付き P(2着=b | 1着=a)。戻り値は (6,6)。対角は0。"""
    m = np.zeros((6, 6))
    for a in range(6):
        tot = q[first_idx == a].sum()
        if tot <= 0:
            continue
        for b in range(6):
            if b == a:
                continue
            m[a, b] = q[(first_idx == a) & (second_idx == b)].sum() / tot
    return m


def build_rows(lanes, meta, q, first_idx, second_idx):
    """(a,b) 30通りぶんの特徴量。並びは PAIRS と同じ。"""
    def col(k):
        return np.array([x.get(k) if x.get(k) is not None else np.nan
                         for x in lanes], dtype=float)
    ast, sts, cst = col("avg_st"), col("st_setsu"), col("c_st")
    cls, nw, m2 = col("cls_val"), col("n_win"), col("m_2ren")
    tj, mp, fc = col("tenji"), col("mot_pure"), col("f_count")
    with np.errstate(invalid="ignore"):
        td = tj - np.nanmean(tj)
    mk = market_second(q, first_idx, second_idx)
    q1 = np.array([q[first_idx == a].sum() for a in range(6)])
    out = []
    for a, b in PAIRS:
        oth = [c for c in range(6) if c not in (a, b)]
        with np.errstate(invalid="ignore"):
            vs_oth = ast[b] - np.nanmean(ast[oth])
        out.append([a, b, np.log(max(mk[a, b], 1e-9)), q1[a],
                    ast[b], ast[b] - ast[a], vs_oth,
                    sts[b], cst[b], cls[b] - cls[a], nw[b],
                    m2[b], td[b], mp[b], fc[b],
                    meta.get("jcd", np.nan),
                    meta.get("wave", np.nan), meta.get("wind", np.nan)])
    return np.array(out, dtype=np.float32), mk


def gmatrix(model, lanes, meta, q, first_idx, second_idx):
    """g(a,b) を返す (6,6)。model が None なら全部 1（＝いまの挙動）。"""
    if model is None:
        return np.ones((6, 6))
    X, mk = build_rows(lanes, meta, q, first_idx, second_idx)
    p = np.asarray(model.predict(X)).ravel()
    P = np.zeros((6, 6))
    for k, (a, b) in enumerate(PAIRS):
        P[a, b] = max(float(p[k]), 1e-9)
    s = P.sum(1, keepdims=True)
    P = P / np.maximum(s, 1e-12)
    g = np.ones((6, 6))
    ok = mk > 0
    g[ok] = P[ok] / mk[ok]
    # ★極端な値を出させない。推定が壊れたときに買い目が暴れるのを防ぐ。
    return np.clip(g, 0.5, 2.0)


def load(model_dir="model"):
    """model/lgb_2nd.txt があれば読む。無ければ None（＝補正なしで動く）。"""
    path = os.path.join(model_dir, "lgb_2nd.txt")
    if not os.path.exists(path):
        return None
    fj = os.path.join(model_dir, "features_2nd.json")
    if os.path.exists(fj):
        with open(fj, encoding="utf-8") as f:
            got = json.load(f)
        if got != FEATS:
            raise SystemExit("★2着モデルの特徴量が second.py と食い違っています。"
                             "学習しなおしてください")
    import lightgbm as lgb
    return lgb.Booster(model_file=path)
