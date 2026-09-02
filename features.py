# -*- coding: utf-8 -*-
"""features.py -- 特徴量の定義。学習(train.py)と当日実行(yosou.py)で必ず共有する。

★ここを1か所にしている理由
  v22 では「学習で作った特徴量」と「本番で作る特徴量」が別コードだったため、
  並びのずれや作り方の食い違いが起きた。v24 では両方がこのファイルを import する。
  特徴量を足すときは、このファイルだけを直せばよい。
"""
import numpy as np

CLS = {"A1": 4, "A2": 3, "B1": 2, "B2": 1}

# 市場(オッズ)から作るもの。v24 で新しく入った系統
MARKET = ["lq", "q_rank", "q_rel", "q_conc", "q_ent"]
# 出走表
CARD = ["lane", "cls_val", "age", "weight", "f_count", "avg_st",
        "n_win", "n_2ren", "l_win", "l_2ren", "m_2ren", "b_2ren"]
# 今節・コース別
SETSU = ["tok", "srank", "genten", "nruns", "st_setsu", "c_win", "c_ren3", "c_st"]
# 開催・その他
META = ["jcd", "rno", "day_no", "n_days", "is_final", "cls_max", "cls_gap",
        "is_f2", "has_f"]
_DEVCOLS = ("n_win", "l_win", "m_2ren", "c_win", "avg_st", "tok", "st_setsu")
_INCOLS = ("n_win", "tok", "m_2ren", "avg_st", "st_setsu")
DEV = [f"{c}_dev" for c in _DEVCOLS]
RK = [f"{c}_rk" for c in _DEVCOLS]
IN = [f"{c}_in" for c in _INCOLS]
# 展示タイム(直前情報)
TENJI = ["tenji", "tenji_dev", "tenji_rk"]
# Kファイル由来(motor.py が作る)
# ★st_pure(Kファイル由来のST純度)を足して試したが、本番の学習器では
#   対数損失が改善しなかったので入れていない。経緯はメモ §17。
PURE = ["mot_pure"]

FEATS = MARKET + CARD + SETSU + META + DEV + RK + IN + TENJI + PURE
CAT = ["jcd"]                       # カテゴリ扱いする特徴量

# 3連単120通りの並び。市場オッズもモデル出力もこの順に揃える
COMBOS = [f"{a}-{b}-{c}" for a in range(1, 7) for b in range(1, 7) if b != a
          for c in range(1, 7) if c not in (a, b)]
CIX = {c: i for i, c in enumerate(COMBOS)}
FIRST = np.array([int(c[0]) - 1 for c in COMBOS])   # 各組の1着艇(0始まり)


def market_probs(odds120):
    """3連単オッズ120個 → 組の市場確率 q(合計1) と 各艇の1着市場確率 q1"""
    od = np.asarray(odds120, dtype=float)
    if od.shape != (120,) or not np.all(od > 0):
        return None, None
    inv = 1.0 / od
    q = inv / inv.sum()
    q1 = np.array([q[FIRST == a].sum() for a in range(6)])
    q1 = q1 / q1.sum()
    return q, q1


def _rank(v, ascending):
    order = np.argsort(v if ascending else -v, kind="stable")
    rk = np.empty(len(v), float)
    rk[order] = np.arange(1, len(v) + 1)
    rk[np.isnan(v)] = np.nan
    return rk


def build_race(lanes, meta, q1):
    """1レース6艇ぶんの特徴量行列 (6, len(FEATS)) を作る。

    lanes : 6個の dict。CARD/SETSU のキーと toban, tenji, mot_pure を持つ
    meta  : {"jcd","rno","day_no","n_days","is_final"}
    q1    : 各艇の1着市場確率(長さ6)。market_probs の戻り値
    """
    d = {}
    for c in CARD + SETSU + ["tenji", "mot_pure"]:
        d[c] = np.array([x.get(c) if x.get(c) is not None else np.nan
                         for x in lanes], dtype=float)
    # 市場
    q1 = np.asarray(q1, dtype=float)
    d["lq"] = np.log(np.clip(q1, 1e-9, None))
    d["q_rank"] = _rank(q1, ascending=False)
    d["q_rel"] = d["lq"] - d["lq"].max()
    d["q_conc"] = np.full(6, q1.max())
    d["q_ent"] = np.full(6, -(q1 * np.log(np.clip(q1, 1e-9, None))).sum())
    # 開催
    for k in ("jcd", "rno", "day_no", "n_days", "is_final"):
        v = meta.get(k)
        d[k] = np.full(6, np.nan if v is None else float(v))
    # 級別
    cv = d["cls_val"]
    d["cls_max"] = np.full(6, np.nanmax(cv) if not np.all(np.isnan(cv)) else np.nan)
    d["cls_gap"] = cv - d["cls_max"]
    f = np.nan_to_num(d["f_count"], nan=0.0)
    d["is_f2"] = (f >= 2).astype(float)
    d["has_f"] = (f >= 1).astype(float)
    # レース内の相対化
    for c in _DEVCOLS + ("tenji",):
        v = d[c]
        allnan = np.all(np.isnan(v))
        d[f"{c}_dev"] = np.full(6, np.nan) if allnan else v - np.nanmean(v)
        d[f"{c}_rk"] = _rank(v, ascending=c in ("avg_st", "st_setsu", "tenji"))
    # 内側の艇との差(枠番順に並んでいる前提)
    for c, big in (("n_win", True), ("tok", True), ("m_2ren", True),
                   ("avg_st", False), ("st_setsu", False)):
        v = d[c]
        z = np.full(6, np.nan)
        z[1:] = (v[1:] - v[:-1]) if big else (v[:-1] - v[1:])
        d[f"{c}_in"] = z
    return np.column_stack([d.get(f, np.full(6, np.nan)) for f in FEATS])


def trifecta(p1, q):
    """1着だけモデルに差し替え、2着3着は市場の条件付き構造を借りる。

        P(a,b,c) = q(a,b,c) × p1(a)/q1(a)   を正規化したもち

    §7-1c で検証済み。カスケード(p2/p3)を作らなくてよい。
    """
    p1 = np.asarray(p1, float); p1 = p1 / p1.sum()
    q = np.asarray(q, float)
    q1 = np.array([q[FIRST == a].sum() for a in range(6)])
    ratio = p1 / np.maximum(q1 / q1.sum(), 1e-12)
    cp = q * ratio[FIRST]
    return cp / cp.sum()


if __name__ == "__main__":
    print(f"特徴量 {len(FEATS)}個")
    for nm, g in (("市場", MARKET), ("出走表", CARD), ("今節", SETSU), ("開催", META),
                  ("レース内偏差", DEV), ("レース内順位", RK), ("内側との差", IN),
                  ("展示", TENJI), ("Kファイル", PURE)):
        print(f"  {nm:<12}{len(g):>3}個  {' '.join(g)}")
    rng = np.random.default_rng(0)
    od = 1.0 / (rng.dirichlet(np.ones(120) * 0.3) * 0.748)
    q, q1 = market_probs(od)
    lanes = [{"lane": i + 1, "cls_val": 2, "age": 30, "weight": 52, "f_count": 0,
              "avg_st": 0.16, "n_win": 5.0, "n_2ren": 0.3, "l_win": 5.0,
              "l_2ren": 0.3, "m_2ren": 0.35, "b_2ren": 0.35, "tok": 6.0,
              "srank": 10, "genten": 0, "nruns": 4, "st_setsu": 0.16,
              "c_win": 20.0, "c_ren3": 40.0, "c_st": 0.16, "tenji": 6.8,
              "mot_pure": 0.01} for i in range(6)]
    X = build_race(lanes, {"jcd": 24, "rno": 1, "day_no": 2, "n_days": 6,
                           "is_final": 0}, q1)
    print(f"\n行列の形 {X.shape}  NaN {int(np.isnan(X).sum())}個")
    cp = trifecta(q1 * np.array([1.2, 1, 1, 1, 1, 0.8]), q)
    print(f"3連単の合計 {cp.sum():.6f}  最大 {cp.max():.4f}")
