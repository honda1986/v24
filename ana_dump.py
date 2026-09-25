# -*- coding: utf-8 -*-
"""ana_dump.py -- 穴側の「買い方」を後から何通りでも試せるように、
   候補になりうる組を全部そのまま落とす（モデルを2度走らせないため）。

   落とすのは odds 2〜60倍の組（既定）。1着=1号艇の組も落とす
   （その条件自体を試すため）。

   ★足切り（淡水・波・風）も外して落とし、代わりに 1レース1個の ok 列を
     持たせる。こうすると足切りそのものを後から検証できる。
     足切りありの数字に戻すには ok==1 で絞ること。
   ★帯側も見られるように p は補正なし/g/g+h の3本とも落とす。
"""
import argparse, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F
import second as S
import third as T
import select_rule as SR
import bt
import lightgbm as lgb

ap = argparse.ArgumentParser()
ap.add_argument("--raw"); ap.add_argument("--tokuten")
ap.add_argument("--pure"); ap.add_argument("--kfile")
ap.add_argument("--model", default="/home/user/v24/model")
ap.add_argument("--from", dest="frm", type=int)
ap.add_argument("--to", dest="to", type=int, default=99999999)
ap.add_argument("--out")
ap.add_argument("--odds-lo", type=float, default=2.0)
ap.add_argument("--odds-hi", type=float, default=60.0)
args = ap.parse_args()

# ★bt.collect は band_ok を通らないレースを捨ててしまう。足切り（淡水・波・風）
#   そのものを検証したいので、ここでは全部通し、
#   従来の足切り(ana_ok)を通ったかどうかを ok 列に残す。
_ana_ok = SR.ana_ok
SR.band_ok = lambda jcd, wave, wind: True

m1 = lgb.Booster(model_file=f"{args.model}/lgb_mf.txt")
model_feats = json.load(open(f"{args.model}/features.json", encoding="utf-8"))
m2 = S.load(args.model); m3 = T.load(args.model)
assert m2 is not None and m3 is not None

races = bt.collect(args)
print(f"レース {len(races):,}", flush=True)

FIRST1 = np.array([int(c[0]) for c in F.COMBOS], dtype=np.float64)
SEC1 = np.array([int(c[2]) for c in F.COMBOS], dtype=np.float64)
THI1 = np.array([int(c[4]) for c in F.COMBOS], dtype=np.float64)
NAMES = ["date", "race", "jcd", "rno", "combo", "first", "second", "third",
         "odds", "q", "p", "hit", "rmin", "band", "wave", "wind", "day_no",
         "is_final", "p1_first", "q1_first", "p_base", "p_g", "ok", "n_days",
         "p_h"]
chunks = []
for rno_, (d, lanes, mt, od, q, q1, hit) in enumerate(races):
    X = F.build_race(lanes, mt, q1, feats=model_feats)
    raw = np.asarray(m1.predict(X), dtype=float)
    p1 = raw / raw.sum()
    base = F.trifecta(p1, q)
    gv = S.gmatrix(m2, lanes, mt, q, F.FIRST, bt.SEC_IDX)[F.FIRST, bt.SEC_IDX]
    hv = T.hvector(m3, lanes, mt, q, F.FIRST, bt.SEC_IDX, bt.THI_IDX)
    p = base * gv * hv; p = p / p.sum()
    pb = base / base.sum()
    pg = (base * gv); pg = pg / pg.sum()
    ph = (base * hv); ph = ph / ph.sum()      # h だけを入れた場合
    band = np.zeros(120)
    band[list(SR.pick(q, p, SR.PQ_MIN_GH))] = 1.0
    hitv = np.zeros(120); hitv[hit] = 1.0
    rmin = float(od.min())
    ok = 1.0 if _ana_ok(mt["jcd"], mt["wave"], mt["wind"]) else 0.0
    i = np.where((od >= args.odds_lo) & (od <= args.odds_hi) & (q > 0))[0]
    if len(i) == 0:
        continue
    n = len(i)
    # ★float32 で持つと 8桁の日付が丸められる（20260131 → 20260132）。
    #   日付で期間を切るので、ここは float64 でなければならない。
    one = lambda v: np.full(n, v, dtype=np.float64)
    chunks.append(np.stack([
        one(d), one(rno_), one(mt["jcd"]), one(mt["rno"]), i.astype(np.float64),
        FIRST1[i], SEC1[i], THI1[i], od[i], q[i], p[i], hitv[i], one(rmin),
        band[i], one(mt["wave"] if mt["wave"] is not None else -1),
        one(mt["wind"] if mt["wind"] is not None else -1),
        one(mt["day_no"] or -1), one(mt["is_final"]),
        p1[FIRST1[i].astype(int) - 1], q1[FIRST1[i].astype(int) - 1],
        pb[i], pg[i], one(ok), one(mt["n_days"] or -1), ph[i]], axis=1))
    if (rno_ + 1) % 10000 == 0:
        print(f"  {rno_+1}/{len(races)}", flush=True)

A = np.concatenate(chunks, axis=0)
np.savez_compressed(args.out, A=A, names=np.array(NAMES))
print(f"保存 {A.shape}  列 {len(NAMES)}")
