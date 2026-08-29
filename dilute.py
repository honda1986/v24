# -*- coding: utf-8 -*-
"""dilute.py -- 直前情報の測定ノイズで、採用ルールの回収率がどれだけ薄まるか

wavecheck.py が実測した「直前 - Kファイル」のずれの分布をそのまま使い、
Kファイル基準で検証した 96.0% が、直前情報基準で運用したときいくつになるかを出す。

  P(このレースが本番で買われる) = P(波+ずれ < 3) × P(風+ずれ < 4)

各レースをこの確率で重みづけして回収率を出し直す。閾値の取り直しではなく、
「いまのルールのまま運用したらどうなるか」を測るもの。
"""
import glob
import gzip
import json

import numpy as np

TANSUI = {1, 2, 5, 10, 11, 12, 13, 21, 23}
# wavecheck.py の実測（660レース、非淡水）
DW = {-5: .006, -2: .032, -1: .108, 0: .691, 1: .120, 2: .033}
DS = {-3: .014, -2: .027, -1: .180, 0: .526, 1: .200, 2: .039, 3: .008}
for d in (DW, DS):                      # 端数を0に寄せて正規化
    s = sum(d.values())
    for k in d:
        d[k] /= s

b = np.load("/root/work/base_tenji_new.npz", allow_pickle=True)
date, od, hit = b["date"], b["odds"], b["hit"]
F0 = list(b["feats"]); X0 = b["X"]; n = len(date)
jcd = X0[:, 0, F0.index("jcd")].astype(int)
rno = X0[:, 0, F0.index("rno")].astype(int)
combos = [(a, c, d) for a in range(6) for c in range(6) for d in range(6)
          if len({a, c, d}) == 3]
names = [f"{a+1}-{c+1}-{d+1}" for a, c, d in combos]
ci = {s: i for i, s in enumerate(names)}
HI = np.array([ci.get(h, -1) for h in hit])
ok = ~np.isnan(od).any(1) & (HI >= 0) & (od > 0).all(1)
inv = 1.0 / np.where(od > 0, od, np.nan).astype(np.float64)
q3 = inv / np.nansum(inv, 1, keepdims=True)
Y = np.zeros_like(q3, bool); Y[np.arange(n), HI] = True
R = np.load("/root/work/R_final.npy").astype(np.float64)
SEL = (q3 >= 0.12) & (q3 < 0.25) & (R > 1.05)

W = {}
for p in sorted(glob.glob("/root/v22_new/kfile/*.json.gz")):
    kd = json.load(gzip.open(p, "rt", encoding="utf-8"))
    d = kd["date"]
    for r in kd.get("races") or []:
        W[(d, r["jcd"], r["rno"])] = (r.get("wind"), r.get("wave"))
wx = np.array([W.get((str(date[i]), int(jcd[i]), int(rno[i])), (None, None))
               for i in range(n)], dtype=object)
wind = np.array([np.nan if x is None else float(x) for x in wx[:, 0]])
wave = np.array([np.nan if x is None else float(x) for x in wx[:, 1]])

umi = np.array([int(j) not in TANSUI for j in jcd])
EV = ok & (date >= 20240301) & umi & ~np.isnan(wave) & ~np.isnan(wind)


def pass_prob(w, s):
    pw = sum(p for d, p in DW.items() if w + d < 3)
    ps = sum(p for d, p in DS.items() if s + d < 4)
    return pw * ps


def roi(mask_race, weight=None):
    s = mask_race[:, None] & SEL
    k = int(s.sum())
    if not k:
        return None
    v = od[s] * Y[s]
    if weight is None:
        return v.mean(), k, 1.0
    ww = np.repeat(weight[mask_race], SEL[mask_race].sum(1))
    return float((v * ww).sum() / ww.sum()), k, float(weight[mask_race].mean())


print(f"評価対象 {int(EV.sum()):,}レース（非淡水・Kファイルの気象あり）")

CALM = (wave < 3) & (wind < 4)
a = roi(EV & CALM)
c = roi(EV & ~CALM)
allr = roi(EV)
print(f"\nKファイル基準（これが検証した 96.0% の正体）")
print(f"  波<3・風<4 で買う     回収 {a[0]*100:5.1f}%  ({a[1]:,}組)")
print(f"  それ以外              回収 {c[0]*100:5.1f}%  ({c[1]:,}組)")
print(f"  気象で切らない        回収 {allr[0]*100:5.1f}%  ({allr[1]:,}組)")

pp = np.array([pass_prob(wave[i], wind[i]) if EV[i] else 0.0 for i in range(n)])
d = roi(EV, pp)
print(f"\n直前情報で運用したとき（ずれの分布で重みづけ）")
print(f"  回収 {d[0]*100:5.1f}%   買う割合 {d[2]*100:.1f}%"
      f"（Kファイル基準では {CALM[EV].mean()*100:.1f}%）")
print(f"  薄まり {(d[0]-a[0])*100:+.1f}pt")

print("\n閾値を締めたらどうなるか（★これは事後の探索。参考値として見ること）")
for wmax, smax in ((3, 4), (2, 4), (3, 3), (2, 3), (1, 4)):
    pq = np.array([(sum(p for dd, p in DW.items() if wave[i] + dd < wmax) *
                    sum(p for dd, p in DS.items() if wind[i] + dd < smax))
                   if EV[i] else 0.0 for i in range(n)])
    r = roi(EV, pq)
    print(f"  直前 波<{wmax}cm・風<{smax}m   回収 {r[0]*100:5.1f}%  "
          f"買う割合 {r[2]*100:5.1f}%")
