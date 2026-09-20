# -*- coding: utf-8 -*-
"""ana_variants.py -- 穴側の「買い方」を総当たりで比べる

  python ana_dump.py --raw v22/raw --tokuten v22/tokuten --kfile v22/kfile \
      --pure pure.npz --from 20250401 --out ana_dump.npz
  python ana_variants.py --dump ana_dump.npz

★ここでやっていることは仕様書 §6-4 の禁止事項（新しい切り口探し）に当たる。
  ユーザーの指示で実施したもので、ここで見つかった買い方は
  **そのまま採用してはいけない**。次の本番データで事前登録して測り直すこと。

期間の分け方
  探索期間 2026/02-09 … いまの穴側ルール（版47）を決めた期間
  独立期間 2025/05-2026/01 … ルール決定に使っていない10か月
両方で同じ向きに出ないものは、採らない。
"""
import argparse
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--dump", required=True)
args = ap.parse_args()
z = np.load(args.dump, allow_pickle=True)
A = z["A"]; names = list(z["names"])
C = {n: A[:, i] for i, n in enumerate(names)}
pq = C["p"] / C["q"]
d = C["date"]
B_ = (d >= 20250501) & (d <= 20260131)     # 独立期間（10か月）
X_ = (d >= 20260201) & (d <= 20260918)     # ルールを決めた期間
print(f"全{len(A):,}行  独立期間{B_.sum():,}行  探索期間{X_.sum():,}行")

def sel(mask, lo, hi, pqmin, rmax, notone=True, noband=True):
    m = mask & (C["odds"] >= lo) & (C["odds"] < hi) & (pq > pqmin) \
        & (C["rmin"] < rmax)
    if notone:
        m &= C["first"] != 1
    if noband:
        m &= C["band"] == 0
    return m

def roi(m):
    if m.sum() == 0:
        return (0, 0, 0, np.nan)
    r = C["hit"][m] * C["odds"][m] * 100.0
    return (len(np.unique(C["race"][m])), int(m.sum()), int(C["hit"][m].sum()),
            r.mean())

print("\n=== 現行ルール（版47）の再現 ===")
for lab, mk in (("独立 2025/05-2026/01", B_), ("探索 2026/02-09", X_)):
    print(f"  {lab}: {roi(sel(mk, 8, 15, 1.097, 8))}")

def boot(m, n=2000, seed=0):
    if m.sum() == 0: return (np.nan, np.nan), np.nan
    r = C["hit"][m] * C["odds"][m] * 100.0
    ri = C["race"][m]
    u = np.unique(ri); ix = {v: k for k, v in enumerate(u)}
    ii = np.array([ix[v] for v in ri]); rng = np.random.default_rng(seed)
    b = np.empty(n)
    for t in range(n):
        w = np.bincount(rng.integers(0, len(u), len(u)), minlength=len(u))[ii]
        b[t] = (r * w).sum() / w.sum() if w.sum() else np.nan
    b = b[~np.isnan(b)]
    return tuple(np.quantile(b, [.025, .975])), float((b > 100).mean())

print("\n\n############ 1. 切り口ごとの単調性（探索期間 vs 独立期間） ############")
print("   ※ 片方でしか単調でない切り口は、使ってはいけない")

def bucket(mask_base, key, edges, lab):
    print(f"\n--- {lab} ---")
    print(f"   {'区間':>14} | {'探索 2026/02-09':>26} | {'独立 2025/05-2026/01':>26}")
    for lo, hi in zip(edges[:-1], edges[1:]):
        line = f"   {lo:>6.2f}〜{hi:<6.2f} |"
        for mk in (X_, B_):
            m = mask_base(mk) & (key >= lo) & (key < hi)
            nr, nb, nh, r = roi(m)
            line += f" {nb:5,}点 的中{nh:3} {r:6.1f}% |" if nb else "      —              |"
        print(line)

# 穴側の土台：1着≠1号艇・帯でない・rmin<8・オッズ8〜15 のうち、p/q だけ動かす
base_pq = lambda mk: mk & (C["first"] != 1) & (C["band"] == 0) \
    & (C["odds"] >= 8) & (C["odds"] < 15) & (C["rmin"] < 8)
bucket(base_pq, pq, [0.8, 1.0, 1.097, 1.2, 1.35, 1.6, 99], "p/q（モデルの強気さ）")

base_od = lambda mk: mk & (C["first"] != 1) & (C["band"] == 0) \
    & (pq > 1.097) & (C["rmin"] < 8)
bucket(base_od, C["odds"], [3, 6, 8, 10, 12, 15, 20, 30, 60], "オッズ")

base_rm = lambda mk: mk & (C["first"] != 1) & (C["band"] == 0) \
    & (pq > 1.097) & (C["odds"] >= 8) & (C["odds"] < 15)
bucket(base_rm, C["rmin"], [1, 3, 4, 5, 6, 7, 8, 10, 15, 999],
       "レース最低オッズ（本命の堅さ）")

base_f = lambda mk: mk & (C["band"] == 0) & (pq > 1.097) \
    & (C["odds"] >= 8) & (C["odds"] < 15) & (C["rmin"] < 8)
bucket(base_f, C["first"], [1, 2, 3, 4, 5, 6, 7], "1着の艇番")

print("\n\n############ 2. 「良い買い方」を探索期間で選ぶと、独立期間で当たるか ############")
print("   1,000通り以上の買い方を作り、探索期間の成績と独立期間の成績を突き合わせる。")
print("   相関が無ければ『探索期間で良く見える買い方』を選ぶ行為そのものに意味が無い。")
grid = []
for lo in (6, 7, 8, 9, 10, 12):
    for hi in (10, 12, 15, 18, 20, 25, 30):
        if hi <= lo: continue
        for pm in (1.0, 1.05, 1.097, 1.15, 1.25):
            for rm in (5, 6, 7, 8, 10, 999):
                for one in (True, False):
                    mb = sel(B_, lo, hi, pm, rm, notone=one)
                    mx = sel(X_, lo, hi, pm, rm, notone=one)
                    if mb.sum() < 150 or mx.sum() < 150: continue
                    grid.append((lo, hi, pm, rm, one, roi(mx)[3], roi(mb)[3],
                                 int(mx.sum()), int(mb.sum())))
G = np.array([(g[5], g[6]) for g in grid])
print(f"\n  条件を満たす買い方 {len(grid):,}通り")
def spearman(a, b):
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])
print(f"  探索期間ROI と 独立期間ROI の順位相関: {spearman(G[:,0], G[:,1]):+.3f}")
print(f"  （+1 なら探索期間の良し悪しがそのまま通じる / 0 なら無関係）")
o = np.argsort(-G[:, 0])
print(f"\n  探索期間の上位20通り → 独立期間での回収率")
print(f"    探索期間ROI 中央値 {np.median(G[o[:20],0]):.1f}%  "
      f"→ 独立期間ROI 中央値 {np.median(G[o[:20],1]):.1f}%")
print(f"  全1,000通りの独立期間ROI 中央値 {np.median(G[:,1]):.1f}%  "
      f"（上位20通りがこれを超えていなければ、選んだ意味が無い）")
print(f"\n  参考: 独立期間で最も良かった買い方（＝後知恵。使ってはいけない）")
ob = np.argsort(-G[:, 1])[:3]
for k in ob:
    lo, hi, pm, rm, one, ra, rb, na, nb = grid[k]
    print(f"    オッズ{lo}〜{hi} p/q>{pm} 最低オッズ<{rm} 1着≠1号艇={one}: "
          f"独立 {rb:.1f}%({nb}点) / 探索 {ra:.1f}%({na}点)")
print(f"  独立期間で100%を超えた買い方: {(G[:,1]>100).sum()}/{len(grid)}通り "
      f"({100*(G[:,1]>100).mean():.0f}%)")
print(f"  探索期間で100%を超えた買い方: {(G[:,0]>100).sum()}/{len(grid)}通り "
      f"({100*(G[:,0]>100).mean():.0f}%)")

both = (G[:, 0] >= 120) & (G[:, 1] >= 120)
print(f"\n  両方の期間で120%以上だった買い方: {both.sum()}/{len(grid)}通り")

print("\n\n############ 3. 見つかった領域が「面」か「点」か ############")
print("   1セルだけ良いのは偶然。隣のセルも同じ向きなら、まだ見込みがある。")
print("   行=レース最低オッズの上限 / 列=オッズ窓。上段=探索期間 下段=独立期間")
for rm in (5, 6, 7, 8, 10, 999):
    print(f"\n  最低オッズ<{rm}")
    for lab, (lo, hi) in (("  8〜10", (8, 10)), (" 10〜12", (10, 12)),
                          (" 12〜15", (12, 15)), (" 15〜20", (15, 20)),
                          (" 8〜15 ", (8, 15))):
        a = roi(sel(X_, lo, hi, 1.0, rm)); b = roi(sel(B_, lo, hi, 1.0, rm))
        print(f"    オッズ{lab}: 探索 {a[3]:6.1f}%({a[1]:4,}点/的中{a[2]:3}) | "
              f"独立 {b[3]:6.1f}%({b[1]:4,}点/的中{b[2]:3})")

print("\n\n############ 4. 賭け方（資金配分）の比較 ############")
print("   買う組は現行ルール（版47）のまま。配分だけ変える。")
def stake_report(m, lab):
    od, hit, ri = C["odds"][m], C["hit"][m], C["race"][m]
    n = len(od)
    if n == 0: return
    u, inv = np.unique(ri, return_inverse=True)
    cnt = np.bincount(inv)
    plans = {
        "1点100円（現行）": np.ones(n),
        "払戻を揃える（賭け金∝1/オッズ）": 1.0 / od,
        "1レース100円を均等割り": 1.0 / cnt[inv],
        "1レース1点だけ（p/q最大）": None,
    }
    print(f"\n  --- {lab} ---")
    for k, w in plans.items():
        if w is None:
            pqm = pq[m]
            best = np.zeros(n, dtype=bool)
            for j in range(len(u)):
                idx = np.where(inv == j)[0]
                best[idx[np.argmax(pqm[idx])]] = True
            w = best.astype(float)
        ret = (hit * od * w).sum() / w.sum() * 100.0
        # レース単位の収支のばらつき
        pl = np.bincount(inv, weights=hit * od * w - w)
        sd = pl.std(ddof=1) / (w.sum() / len(u))
        cum = np.cumsum(pl[np.argsort(u)])
        dd = (np.maximum.accumulate(cum) - cum).max() / (w.sum() / len(u))
        print(f"    {k:<32} 回収率 {ret:6.1f}%  "
              f"レース毎損益の標準偏差 {sd:5.2f}倍  最大下落 {dd:6.1f}レース分")
stake_report(sel(X_, 8, 15, 1.097, 8), "探索 2026/02-09")
stake_report(sel(B_, 8, 15, 1.097, 8), "独立 2025/05-2026/01")

print("\n\n############ 5. 『両方で良い』は偶然でどれだけ出るか ############")
pA = (G[:, 0] >= 120).mean(); pB = (G[:, 1] >= 120).mean()
print(f"  探索期間で120%以上: {pA*100:.1f}%  独立期間で120%以上: {pB*100:.1f}%")
print(f"  両者が無関係なら期待される『両方で120%以上』: "
      f"{len(grid)*pA*pB:.1f}通り  実際: {both.sum()}通り")

print("\n\n############ 6. 12〜15倍 × レース最低オッズ<6 を個別に検定 ############")
for lab, mk in (("探索 2026/02-09", X_), ("独立 2025/05-2026/01", B_)):
    for pm, pl in ((1.0, "p/q 条件なし"), (1.097, "p/q>1.097")):
        m = sel(mk, 12, 15, pm, 6)
        nr, nb, nh, r = roi(m)
        (lo, hi), pw = boot(m)
        print(f"  {lab} / {pl:<12}: {nr:3}レース {nb:4}点 的中{nh:3} "
              f"回収率 {r:6.1f}%  95%区間 [{lo:.0f}, {hi:.0f}]  P(>100%) {pw:.2f}")
m2p = sel(B_, 12, 15, 1.0, 6) | sel(X_, 12, 15, 1.0, 6)
nr, nb, nh, r = roi(m2p); (lo, hi), pw = boot(m2p)
print(f"  通し（2025/05-2026/09）         : {nr:3}レース {nb:4}点 的中{nh:3} "
      f"回収率 {r:6.1f}%  95%区間 [{lo:.0f}, {hi:.0f}]  P(>100%) {pw:.2f}")

print("\n  月別（12〜15倍 × 最低オッズ<6 / p/q条件なし）")
mm = sel(B_ | X_, 12, 15, 1.0, 6)
ym = (C["date"][mm] // 100).astype(int)
od, hit = C["odds"][mm], C["hit"][mm]
for y in np.unique(ym):
    k = ym == y
    print(f"    {y}  {k.sum():3}点 的中{int(hit[k].sum()):2}  "
          f"{(hit[k]*od[k]*100).mean():6.1f}%")

print("\n\n############ 7. 現行ルールの各部品が独立期間で生きているか ############")
parts = [
    ("1着≠1号艇", sel(B_, 8, 15, 1.097, 8, notone=True),
     sel(B_, 8, 15, 1.097, 8, notone=False) & (C["first"] == 1)),
    ("最低オッズ<8", sel(B_, 8, 15, 1.097, 8), 
     sel(B_, 8, 15, 1.097, 999) & (C["rmin"] >= 8)),
    ("p/q>1.097", sel(B_, 8, 15, 1.097, 8),
     sel(B_, 8, 15, 0.0, 8) & (pq <= 1.097)),
]
for lab, keep, drop in parts:
    a = roi(keep); b = roi(drop)
    print(f"  {lab:<12} 採る側 {a[3]:6.1f}%({a[1]:4,}点) / 捨てる側 {b[3]:6.1f}%"
          f"({b[1]:4,}点)  差 {a[3]-b[3]:+6.1f}pt")

print("\n\n############ 8. 100円/点で実際にいくらになったか ############")
for lab, m in (("版47 8〜15倍/最低<8/p/q>1.097 独立", sel(B_, 8, 15, 1.097, 8)),
               ("版47 同上 探索", sel(X_, 8, 15, 1.097, 8)),
               ("候補 12〜15倍/最低<6 独立", sel(B_, 12, 15, 1.0, 6)),
               ("候補 12〜15倍/最低<6 探索", sel(X_, 12, 15, 1.0, 6))):
    n = int(m.sum()); back = float((C["hit"][m] * C["odds"][m] * 100).sum())
    print(f"  {lab:<34} 投資 {n*100:7,.0f}円 → 回収 {back:8,.0f}円 "
          f"（{back-n*100:+8,.0f}円）")
