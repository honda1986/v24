# -*- coding: utf-8 -*-
"""ana_dump.py -- 穴側の「買い方」を後から何通りでも試せるように、
   候補になりうる組を全部そのまま落とす（モデルを2度走らせないため）。

   落とすのは odds 3〜60倍の組だけ。ここを外れる組は穴側の候補に
   どのみちならない。1着=1号艇の組も落とす（その条件自体を試すため）。
"""
import argparse, os, sys
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
args = ap.parse_args()

m1 = lgb.Booster(model_file=f"{args.model}/lgb_mf.txt")
m2 = S.load(args.model); m3 = T.load(args.model)
assert m2 is not None and m3 is not None

races = bt.collect(args)
print(f"レース {len(races):,}", flush=True)

FIRST1 = np.array([int(c[0]) for c in F.COMBOS])
SEC1 = np.array([int(c[2]) for c in F.COMBOS])
THI1 = np.array([int(c[4]) for c in F.COMBOS])
cols = []
for rno_, (d, lanes, mt, od, q, q1, hit) in enumerate(races):
    X = F.build_race(lanes, mt, q1)
    raw = np.asarray(m1.predict(X), dtype=float)
    p1 = raw / raw.sum()
    base = F.trifecta(p1, q)
    gv = S.gmatrix(m2, lanes, mt, q, F.FIRST, bt.SEC_IDX)[F.FIRST, bt.SEC_IDX]
    hv = T.hvector(m3, lanes, mt, q, F.FIRST, bt.SEC_IDX, bt.THI_IDX)
    p = base * gv * hv
    p = p / p.sum()
    band = np.zeros(120, dtype=bool)
    band[list(SR.pick(q, p, SR.PQ_MIN_GH))] = True
    rmin = float(od.min())
    sel = np.where((od >= 3.0) & (od <= 60.0) & (q > 0))[0]
    for i in sel:
        cols.append((d, rno_, mt["jcd"], mt["rno"], i, FIRST1[i], SEC1[i],
                     THI1[i], od[i], q[i], p[i], 1.0 if i == hit else 0.0,
                     rmin, 1.0 if band[i] else 0.0,
                     mt["wave"] if mt["wave"] is not None else -1,
                     mt["wind"] if mt["wind"] is not None else -1,
                     mt["day_no"] if mt["day_no"] else -1,
                     mt["is_final"], p1[FIRST1[i] - 1], q1[FIRST1[i] - 1]))
    if (rno_ + 1) % 5000 == 0:
        print(f"  {rno_+1}/{len(races)}  {len(cols):,}行", flush=True)

A = np.array(cols, dtype=np.float64)
np.savez_compressed(args.out, A=A, names=np.array(
    ["date", "race", "jcd", "rno", "combo", "first", "second", "third",
     "odds", "q", "p", "hit", "rmin", "band", "wave", "wind", "day_no",
     "is_final", "p1_first", "q1_first"]))
print(f"保存 {A.shape}")
