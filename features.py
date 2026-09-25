# -*- coding: utf-8 -*-
"""features.py -- 特徴量の定義。学習(train.py)と当日実行(yosou.py)で必ず共有する。

★ここを1か所にしている理由
  v22 では「学習で作った特徴量」と「本番で作る特徴量」が別コードだったため、
  並びのずれや作り方の食い違いが起きた。v24 では両方がこのファイルを import する。
  特徴量を足すときは、このファイルだけを直せばよい。
"""
import math

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
# 水面気象。★2026-09-23 に追加。これ以前に学習したモデルには入っていない。
#   build_race は model/features.json に書かれた並びで作るので、
#   古いモデルはこの4つを受け取らないまま動き続ける（yosou.py / bt.py）。
#   w_along は追い風で正、w_cross は左からの風で正。どちらも風速を掛けてある
#   ので、無風なら自然に 0 になる（band_howto.md §18）。
WEATHER = ["wave", "wind", "w_along", "w_cross"]

FEATS = MARKET + CARD + SETSU + META + DEV + RK + IN + TENJI + PURE + WEATHER
CAT = ["jcd"]                       # カテゴリ扱いする特徴量

# 各場の水面の向き（直前情報の is-direction<N>）。band_howto.md §17-2。
# 2026-09-23 に全24場ぶん取得。日をまたいだ不一致ゼロ、パリティ検査 35/35 通過。
VENUE_DIR = {1: 14, 2: 16, 3: 4, 4: 5, 5: 9, 6: 13, 7: 11, 8: 9,
             9: 8, 10: 14, 11: 13, 12: 13, 13: 10, 14: 15, 15: 7, 16: 13,
             17: 11, 18: 7, 19: 11, 20: 10, 21: 1, 22: 2, 23: 12, 24: 3}
WIND_DEG = {"北": 0, "北東": 45, "東": 90, "南東": 135,
            "南": 180, "南西": 225, "西": 270, "北西": 315}


def wind_w(jcd, wind_dir):
    """Kファイルの風向(方位) → 水面基準の w(1..16)。無風・不明は None。

    方位 = (w - direction - 8) × 22.5 の逆算（band_howto.md §17-1）。
    本番は直前情報の is-wind<N> がそのまま w なので、この関数は要らない。
    過去データ(Kファイル)を同じ尺度に直すためだけに使う。
    """
    try:
        d = VENUE_DIR[int(jcd)]
    except (KeyError, TypeError, ValueError):
        return None
    deg = WIND_DEG.get(wind_dir)
    if deg is None:
        return None
    return ((round(deg / 22.5) + d + 8 - 1) % 16) + 1


def kfile_as_before(kw, date, jcd, rno):
    """Kファイルの気象 {(日付,場,R): (波高,風速,風向)} から、本番の直前情報に
    相当する値を返す。

    ★直前情報のレース N の気象は Kファイルのレース N-1 と同じだった
      （band_howto.md §17-1、22/22 一致）。本番のモデルは直前情報しか
      見られないので、学習・検証でも N-1 を使う。N を使うとレース時点の
      風（本番では分からない値）で学習してしまう。
      1R は前が無いので 1R 自身で代用する。
    """
    none = (None, None, None)
    if rno > 1 and (date, jcd, rno - 1) in kw:
        return kw[(date, jcd, rno - 1)]
    return kw.get((date, jcd, rno), none) if rno == 1 else none

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


def build_race(lanes, meta, q1, feats=None):
    """1レース6艇ぶんの特徴量行列 (6, len(feats)) を作る。

    lanes : 6個の dict。CARD/SETSU のキーと toban, tenji, mot_pure を持つ
    meta  : {"jcd","rno","day_no","n_days","is_final","wave","wind","wind_w"}
            wave/wind/wind_w は無くてもよい（その場合 NaN になる）
    q1    : 各艇の1着市場確率(長さ6)。market_probs の戻り値
    feats : 作る特徴量の並び。省略すると FEATS。
            ★古いモデルを動かすときは model/features.json の並びを渡すこと。
              いまの FEATS より短くてよいが、知らない名前があれば止まる。
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
    # 水面気象。w=5 が追い風、w=13 が向かい風、w=9 が左から、w=1 が右から
    # （band_howto.md §18-1）。風速が取れていなければ向きも使わない。
    # meta["fx"] があればそちらを使う（bt.py: 足切りはレース時の値、
    # モデルには直前情報相当の値、と分けるため）
    wx = meta.get("fx") or meta
    wave, wind, ww = wx.get("wave"), wx.get("wind"), wx.get("wind_w")
    d["wave"] = np.full(6, np.nan if wave is None or float(wave) < 0
                        else float(wave))
    sp = np.nan if wind is None or float(wind) < 0 else float(wind)
    d["wind"] = np.full(6, sp)
    if sp != sp:                        # NaN。風速が無ければ向きも分からない
        al = cr = np.nan
    elif ww is None or not (1 <= int(ww) <= 16):
        al = cr = 0.0                   # 無風(w=17)や向き不明。押す力は無い
    else:
        th = math.radians((int(ww) - 5) * 22.5)
        al, cr = sp * math.cos(th), sp * math.sin(th)
    d["w_along"] = np.full(6, al)
    d["w_cross"] = np.full(6, cr)

    want = FEATS if feats is None else list(feats)
    # ★黙って NaN で埋めない。名前のずれは必ず止めて気づけるようにする
    miss = [f for f in want if f not in d]
    if miss:
        raise KeyError(f"features.py が作れない特徴量です: {miss[:5]}")
    return np.column_stack([d[f] for f in want])


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
