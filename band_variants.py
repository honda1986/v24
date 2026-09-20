# -*- coding: utf-8 -*-
"""band_variants.py -- 帯（本線）の買い方を探索期間/独立期間の2分割で比べる

  python ana_dump.py --raw v22/raw --tokuten v22/tokuten --kfile v22/kfile \
      --pure pure.npz --from 20250401 --out dump.npz
  python band_variants.py --dump dump.npz

期間の分け方
  探索期間 2026/02-09 … いまの帯のしきい値を決めた期間
  独立期間 2025/05-2026/01 … しきい値決定に使っていない10か月

★帯は本線（実弾）なので、穴側と違って「採用するかどうか」ではなく
  「いまの形のままでよいか」を見る。切り口を増やす目的ではない。
"""
import argparse
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--dump", required=True)
args = ap.parse_args()
z = np.load(args.dump, allow_pickle=True)
A = z["A"].astype(np.float64)
names = list(z["names"])
C = {n: A[:, i] for i, n in enumerate(names)}
d, q, od, hit, ri = C["date"], C["q"], C["odds"], C["hit"], C["race"]
OK = C["ok"] == 1
B_ = (d >= 20250501) & (d <= 20260131)
X_ = (d >= 20260201) & (d <= 20260918)
PQ = {"補正なし": C["p_base"] / q, "g のみ": C["p_g"] / q, "g+h": C["p"] / q}
TANSUI = {1, 2, 5, 10, 11, 12, 13, 21, 23}
tansui = np.isin(C["jcd"].astype(int), list(TANSUI))
print(f"全{len(A):,}行  足切り後{OK.sum():,}行  "
      f"独立{(B_&OK).sum():,}行  探索{(X_&OK).sum():,}行")

def roi(m):
    if m.sum() == 0:
        return (0, 0, 0, np.nan)
    r = hit[m] * od[m] * 100.0
    return (len(np.unique(ri[m])), int(m.sum()), int(hit[m].sum()), r.mean())

def boot(m, n=2000, seed=0):
    if m.sum() == 0:
        return (np.nan, np.nan), np.nan
    r = hit[m] * od[m] * 100.0
    u, inv = np.unique(ri[m], return_inverse=True)
    rng = np.random.default_rng(seed)
    b = np.empty(n)
    for t in range(n):
        w = np.bincount(rng.integers(0, len(u), len(u)), minlength=len(u))[inv]
        b[t] = (r * w).sum() / w.sum() if w.sum() else np.nan
    b = b[~np.isnan(b)]
    return tuple(np.quantile(b, [.025, .975])), float((b > 100).mean())

def band(mask, qlo=0.12, qhi=0.25, pqmin=1.097, key="g+h", useok=True):
    m = mask & (q >= qlo) & (q < qhi) & (PQ[key] > pqmin)
    return m & OK if useok else m

print("\n=== 現行の帯（q 0.12〜0.25 / p/q>1.097 / g+h / 足切りあり）===")
for lab, mk in (("探索 2026/02-09", X_), ("独立 2025/05-2026/01", B_)):
    nr, nb, nh, r = roi(band(mk))
    (lo, hi), pw = boot(band(mk))
    print(f"  {lab}: {nr:,}レース {nb:,}点 的中{nh}本 回収率 {r:.1f}% "
          f"95%区間 [{lo:.0f}, {hi:.0f}] P(>100%) {pw:.2f}")

print("\n\n############ 1. q の窓（0.12〜0.25）は独立期間でも正しいか ############")
print("   p/q>1.097・g+h・足切りあり。q だけ動かす")
print(f"   {'q':>12} | {'探索 2026/02-09':>24} | {'独立 2025/05-2026/01':>24}")
edges = [0.04, 0.08, 0.10, 0.12, 0.15, 0.18, 0.21, 0.25, 0.30, 0.40]
for lo, hi in zip(edges[:-1], edges[1:]):
    line = f"   {lo:.2f}〜{hi:.2f} |"
    for mk in (X_, B_):
        nr, nb, nh, r = roi(band(mk, lo, hi))
        line += f" {nb:6,}点 的中{nh:4} {r:6.1f}% |" if nb else "        —            |"
    print(line + ("  ← 現行の帯" if (lo, hi) in ((0.12, 0.15),) else ""))

print("\n\n############ 2. p/q のしきい値を動かす ############")
print(f"   {'p/q>':>6} | {'探索 2026/02-09':>24} | {'独立 2025/05-2026/01':>24}")
for t in (1.00, 1.03, 1.05, 1.078, 1.097, 1.12, 1.15, 1.20, 1.30):
    line = f"   {t:5.3f} |"
    for mk in (X_, B_):
        nr, nb, nh, r = roi(band(mk, pqmin=t))
        line += f" {nb:6,}点 的中{nh:4} {r:6.1f}% |" if nb else "        —            |"
    print(line + ("  ← 現行" if abs(t - 1.097) < 1e-6 else ""))

print("\n\n############ 3. 2着/3着の補正は独立期間でも効くか ############")
print("   点数を揃えて比べる（しきい値ではなく p/q 上位N点）")
for mk, lab in ((X_, "探索 2026/02-09"), (B_, "独立 2025/05-2026/01")):
    print(f"\n  --- {lab} ---")
    for nb in (800, 1200, 1900, 2800):
        line = f"    上位{nb:5,}点 "
        for k in ("補正なし", "g のみ", "g+h"):
            m0 = mk & (q >= 0.12) & (q < 0.25) & OK
            idx = np.where(m0)[0]
            if len(idx) < nb:
                line += f" {k}: —"
                continue
            s = idx[np.argsort(-PQ[k][idx])[:nb]]
            r = (hit[s] * od[s] * 100.0).mean()
            line += f" {k} {r:6.1f}% |"
        print(line)

print("\n\n############ 4. 足切り（淡水・波・風）は独立期間でも効くか ############")
print("   q 0.12〜0.25 / p/q>1.097 / g+h。足切りを外した母集団で切り分ける")
raw_band = lambda mk: mk & (q >= 0.12) & (q < 0.25) & (PQ["g+h"] > 1.097)
def cmp2(lab, sub):
    line = f"   {lab:<22}|"
    for mk in (X_, B_):
        nr, nb, nh, r = roi(raw_band(mk) & sub)
        line += f" {nb:6,}点 的中{nh:4} {r:6.1f}% |" if nb else "        —            |"
    print(line)
print(f"   {'':<22}| {'探索 2026/02-09':>24} | {'独立 2025/05-2026/01':>24}")
cmp2("足切りあり（現行）", OK)
cmp2("足切りなし（全部買う）", np.ones(len(A), bool))
cmp2("淡水9場のみ", tansui)
cmp2("淡水以外", ~tansui)
print("   --- 淡水以外で、波だけ動かす（風の条件は外す）---")
for lo, hi in ((-2, 0), (0, 1), (1, 3), (3, 5), (5, 10), (10, 99)):
    cmp2(f"  波 {lo}〜{hi}cm", (~tansui) & (C["wave"] >= lo) & (C["wave"] < hi))
print("   --- 淡水以外で、風だけ動かす（波の条件は外す）---")
for lo, hi in ((-2, 0), (0, 2), (2, 4), (4, 6), (6, 9), (9, 99)):
    cmp2(f"  風 {lo}〜{hi}m", (~tansui) & (C["wind"] >= lo) & (C["wind"] < hi))

print("\n\n############ 5. 足切りの内訳（どれが効いているのか）############")
base = lambda mk: raw_band(mk) & (~tansui)
for lab, sub in (("淡水を外しただけ", lambda mk: base(mk)),
                 ("＋波0〜2cm", lambda mk: base(mk) & (C["wave"] >= 0) & (C["wave"] < 3)),
                 ("＋風<4m", lambda mk: base(mk) & (C["wind"] >= 0) & (C["wind"] < 4)),
                 ("＋波と風の両方（現行）", lambda mk: raw_band(mk) & OK)):
    line = f"   {lab:<22}|"
    for mk in (X_, B_):
        nr, nb, nh, r = roi(sub(mk))
        line += f" {nb:6,}点 的中{nh:4} {r:6.1f}% |"
    print(line)

print("\n\n############ 6. しきい値を上げた場合（両期間で検定）############")
for t in (1.097, 1.12, 1.15):
    for lab, mk in (("探索", X_), ("独立", B_)):
        m = band(mk, pqmin=t)
        nr, nb, nh, r = roi(m); (lo, hi), pw = boot(m)
        print(f"   p/q>{t:5.3f} {lab}: {nb:5,}点 的中{nh:4} 回収率 {r:6.1f}% "
              f"95%区間 [{lo:5.0f},{hi:5.0f}] P(>100%) {pw:.2f}")
    m = band(B_ | X_, pqmin=t)
    nr, nb, nh, r = roi(m); (lo, hi), pw = boot(m)
    print(f"   p/q>{t:5.3f} 通し: {nb:5,}点 的中{nh:4} 回収率 {r:6.1f}% "
          f"95%区間 [{lo:5.0f},{hi:5.0f}] P(>100%) {pw:.2f}")
    print()

print("\n############ 7. 賭け方（資金配分）############")
def stake(m, lab):
    o, h, r_ = od[m], hit[m], ri[m]
    n = len(o)
    u, inv = np.unique(r_, return_inverse=True)
    cnt = np.bincount(inv)
    pqm = PQ["g+h"][m]
    best = np.zeros(n, bool)
    for j in range(len(u)):
        k = np.where(inv == j)[0]
        best[k[np.argmax(pqm[k])]] = True
    for k, w in (("1点100円（現行）", np.ones(n)),
                 ("払戻を揃える（∝1/オッズ）", 1.0 / o),
                 ("1レース100円を均等割り", 1.0 / cnt[inv]),
                 ("1レース1点（p/q最大）", best.astype(float))):
        ret = (h * o * w).sum() / w.sum() * 100.0
        pl = np.bincount(inv, weights=h * o * w - w)
        unit = w.sum() / len(u)
        cum = np.cumsum(pl[np.argsort(u)])
        dd = (np.maximum.accumulate(cum) - cum).max() / unit
        print(f"    {k:<26} 回収率 {ret:6.1f}%  最大下落 {dd:6.1f}レース分")
for lab, mk in (("探索 2026/02-09", X_), ("独立 2025/05-2026/01", B_)):
    print(f"\n  --- {lab} ---"); stake(band(mk), lab)

print("\n\n############ 8. 買い方を探索期間で選ぶと独立期間で当たるか ############")
grid = []
for ql in (0.08, 0.10, 0.12, 0.14):
    for qh in (0.18, 0.21, 0.25, 0.30):
        for t in (1.05, 1.078, 1.097, 1.12, 1.15, 1.18):
            for key in ("補正なし", "g のみ", "g+h"):
                for useok in (True, False):
                    mb = band(B_, ql, qh, t, key, useok)
                    mx = band(X_, ql, qh, t, key, useok)
                    if mb.sum() < 300 or mx.sum() < 300:
                        continue
                    grid.append((roi(mx)[3], roi(mb)[3]))
G = np.array(grid)
ra, rb = np.argsort(np.argsort(G[:, 0])), np.argsort(np.argsort(G[:, 1]))
o = np.argsort(-G[:, 0])
print(f"  買い方 {len(G):,}通り  順位相関 {np.corrcoef(ra, rb)[0,1]:+.3f}")
print(f"  探索期間の上位20通り → 独立期間 中央値 {np.median(G[o[:20],1]):.1f}% "
      f"（全体の中央値 {np.median(G[:,1]):.1f}%）")
print(f"  独立期間で100%超え {(G[:,1]>100).sum()}/{len(G)}通り  "
      f"探索期間で100%超え {(G[:,0]>100).sum()}/{len(G)}通り")

print("\n\n############ 9. 100円/点でいくらになったか ############")
for t in (1.097, 1.15):
    for lab, mk in (("独立", B_), ("探索", X_)):
        m = band(mk, pqmin=t)
        n = int(m.sum()); back = float((hit[m] * od[m] * 100).sum())
        print(f"  p/q>{t} {lab}: 投資 {n*100:8,.0f}円 → 回収 {back:9,.0f}円 "
              f"（{back-n*100:+9,.0f}円）")

print("\n\n############ 10. 波・風の足切りを省いた場合のしきい値 ############")
print("   淡水除外だけ残し、波・風を課さない母集団で p/q を掃引する。")
print("   足切りで捨てていたぶんは、しきい値を上げて埋める必要がある。")
noww = (~tansui) & (q >= 0.12) & (q < 0.25)
cur = OK & (q >= 0.12) & (q < 0.25)
print(f"   {'p/q>':>6} | {'探索 点数 回収率':>20} | {'独立 点数 回収率':>20} |"
      f" {'通し 点数 回収率 95%区間 P(>100%)':>40} | 100円/点")
for t in (1.10, 1.12, 1.13, 1.14, 1.15, 1.16, 1.17, 1.18, 1.20):
    line = f"   {t:6.3f} |"
    for mk in (X_, B_):
        m = mk & noww & (PQ["g+h"] > t)
        line += f" {int(m.sum()):5,} {(hit[m]*od[m]*100).mean():6.1f}% |"
    m = noww & (PQ["g+h"] > t) & (X_ | B_)
    n = int(m.sum()); r = (hit[m] * od[m] * 100).mean()
    (lo, hi), pw = boot(m); back = float((hit[m] * od[m] * 100).sum())
    line += (f" {n:5,} {r:6.1f}% [{lo:3.0f},{hi:3.0f}] P={pw:.2f} |"
             f" {back-n*100:+8,.0f}円")
    print(line)
print("\n   現行(足切りあり・p/q>1.097)と同じ点数に揃えた場合")
for mk, lab in ((X_, "探索"), (B_, "独立")):
    N = int((cur & (PQ["g+h"] > 1.097) & mk).sum())
    idx = np.where(noww & mk)[0]
    s = idx[np.argsort(-PQ["g+h"][idx])[:N]]
    m0 = cur & (PQ["g+h"] > 1.097) & mk
    print(f"     {lab}: 現行{N:,}点 → 波風なしなら p/q>{PQ['g+h'][s].min():.3f} "
          f"で同じ{N:,}点・回収率 {(hit[s]*od[s]*100).mean():.1f}%"
          f"（現行 {(hit[m0]*od[m0]*100).mean():.1f}%）")
