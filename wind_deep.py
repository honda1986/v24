# -*- coding: utf-8 -*-
"""wind_deep.py -- 帯の「風の足切り」を掘り下げる

  python wind_deep.py <dump.npz> <v22/kfile>

風速のカットオフ、風速そのものの効き方、風×波の交互作用、風向（kfile の
wind_dir）、点数を揃えた比較まで、探索期間と独立期間の両方で見る。

★結論は band_howto.md §10。要点だけ先に言うと、風の足切りには独立した根拠が
  無い。捨てている側（風>=4m）は独立期間で100%を超えており、点数を揃えると
  優劣が期間ごとに入れ替わる。風向は完全に使えない。
"""
import numpy as np, gzip, json, glob, os, sys, collections
dump, kdir = sys.argv[1], sys.argv[2]
z=np.load(dump,allow_pickle=True); A=z["A"].astype(np.float64)
C={n:A[:,i] for i,n in enumerate(list(z["names"]))}
d,q,od,hit,ri=C["date"],C["q"],C["odds"],C["hit"],C["race"]; pq=C["p"]/q
B_=(d>=20250501)&(d<=20260131); X_=(d>=20260201)&(d<=20260918)
tan=np.isin(C["jcd"].astype(int),[1,2,5,10,11,12,13,21,23])
have=(C["wave"]>=0)&(C["wind"]>=0); inq=(q>=0.12)&(q<0.25)
BASE=(~tan)&inq&have        # 淡水以外・直前情報あり。ここから風を調べる

# --- kfile から wind_dir / weather / winner を結合 ---
key=(d*10000+C["jcd"]*100+C["rno"]).astype(np.int64)
wd={}; we={}; win={}
for path in sorted(glob.glob(f"{kdir}/*.json.gz")):
    dt=int(os.path.basename(path)[:8])
    if dt<20250401: continue
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for r in json.load(f)["races"]:
            k=dt*10000+r["jcd"]*100+r["rno"]
            wd[k]=r.get("wind_dir"); we[k]=r.get("weather")
            for e in r.get("entries",[]):
                if e.get("chaku")=="01": win[k]=e.get("lane")
DIRS=sorted({v for v in wd.values() if v})
DI={v:i for i,v in enumerate(DIRS)}
wdir=np.array([DI.get(wd.get(int(k)),-1) for k in key])
wthr=np.array([hash(we.get(int(k)) or "")%100000 for k in key])
wname={ (we.get(int(k)) or ""):None for k in key}
winner=np.array([win.get(int(k),-1) for k in key])
print(f"風向の種類 {len(DIRS)}: {DIRS}")
print(f"風向が結合できた行 {100*(wdir>=0).mean():.1f}%  "
      f"勝者が分かる行 {100*(winner>0).mean():.1f}%")

def roi(m):
    if m.sum()==0: return (0,0,np.nan,np.nan)
    return (int(m.sum()),int(hit[m].sum()),(hit[m]*od[m]*100).mean(),
            hit[m].sum()/q[m].sum())
def boot(m,n=2000,seed=0):
    if m.sum()<20: return (np.nan,np.nan),np.nan
    r=hit[m]*od[m]*100.0; u,inv=np.unique(ri[m],return_inverse=True)
    rng=np.random.default_rng(seed); b=np.empty(n)
    for t in range(n):
        w=np.bincount(rng.integers(0,len(u),len(u)),minlength=len(u))[inv]
        b[t]=(r*w).sum()/w.sum()
    return np.quantile(b,[.025,.975]),float((b>100).mean())

print("\n\n#### 1. 風速カットオフ × p/q の2次元 ####")
print("   淡水以外・波は問わない。◎=両期間100%超")
print(f"   {'風<':>4} |" + "".join(f"{t:^17}" for t in (1.13,1.15,1.16,1.18,1.20)))
for wc in (2,3,4,5,6,8,99):
    line=f"   {wc:3}m |"
    for t in (1.13,1.15,1.16,1.18,1.20):
        mx=X_&BASE&(C["wind"]<wc)&(pq>t); mb=B_&BASE&(C["wind"]<wc)&(pq>t)
        nx,_,rx,_=roi(mx); nb,_,rb,_=roi(mb)
        tot=(X_|B_)&BASE&(C["wind"]<wc)&(pq>t)
        n,_,r,_=roi(tot)
        ok="◎" if (rx>100 and rb>100 and nx>=100 and nb>=100) else " "
        line+=f" {n:5,} {r:6.1f}%{ok}"
    print(line)

print("\n\n#### 2. 有力な組み合わせの内訳 ####")
for wc in (3,4,5,99):
    print(f"\n  --- 風<{wc}m ---")
    for t in (1.13,1.15,1.16,1.17,1.18):
        mx=X_&BASE&(C["wind"]<wc)&(pq>t); mb=B_&BASE&(C["wind"]<wc)&(pq>t)
        mt=(X_|B_)&BASE&(C["wind"]<wc)&(pq>t)
        nx,_,rx,_=roi(mx); nb,_,rb,_=roi(mb); n,h,r,im=roi(mt)
        (lo,hi),pw=boot(mt)
        print(f"    p/q>{t}: 探索 {nx:5,}点 {rx:6.1f}% | 独立 {nb:5,}点 {rb:6.1f}% "
              f"| 通し {n:5,}点 {r:6.1f}% [{lo:3.0f},{hi:3.0f}] P={pw:.2f} "
              f"実測/市場 {im:.3f}" + ("  ◎" if rx>100 and rb>100 else ""))

print("\n\n#### 3. 風速そのものの効き方（p/q>1.16・淡水以外）####")
print("   実測/市場 が 1.337 を超えていれば、その風速帯では勝てている")
print(f"   {'風':>8} |" + f"{'探索 2026/02-09':>32}|{'独立 2025/05-2026/01':>32}")
for lo_,hi_ in ((0,1),(1,2),(2,3),(3,4),(4,5),(5,6),(6,8),(8,99)):
    line=f"   {lo_}〜{hi_}m |"
    for mk in (X_,B_):
        m=mk&BASE&(C["wind"]>=lo_)&(C["wind"]<hi_)&(pq>1.16)
        n,h,r,im=roi(m)
        line+=f" {n:5,}点 的中{h:3} {r:6.1f}% 実測/市場{im:5.2f} |" if n else \
              f"{'—':>32}|"
    print(line)

print("\n\n#### 4. 風 × 波（p/q>1.16・淡水以外）####")
print(f"   {'':>16}|" + f"{'探索':>20}|{'独立':>20}")
for wl,wh in ((0,3),(3,99)):
    for vl,vh in ((0,3),(3,99)):
        line=f"   風{wl}〜{wh} 波{vl}〜{vh}|"
        for mk in (X_,B_):
            m=(mk&BASE&(C["wind"]>=wl)&(C["wind"]<wh)
               &(C["wave"]>=vl)&(C["wave"]<vh)&(pq>1.16))
            n,h,r,im=roi(m)
            line+=f" {n:5,}点 {r:6.1f}% |" if n else f"{'—':>20}|"
        print(line)

print("\n\n#### 5. 直前情報が取れていないレース ####")
nohave=(~tan)&inq&(~have)
for t in (1.15,1.16,1.18):
    for lab,mk in (("探索",X_),("独立",B_)):
        m=mk&nohave&(pq>t); n,h,r,im=roi(m)
        print(f"   p/q>{t} {lab}: {n:4,}点 的中{h:3} "
              f"回収率 {r:6.1f}%" if n else f"   p/q>{t} {lab}: なし")

print("\n\n#### 6. 『風が強いのに波が立っていない』レースを外す案 ####")
print("   §4 で 風>=3m かつ 波<3cm が両期間で89%台と一貫して悪かった")
BAD=(C["wind"]>=3)&(C["wave"]<3)
print(f"   {'p/q>':>6} |{'探索':>18}|{'独立':>18}|"
      f"{'通し 回収率 95%区間 P':>34}")
for t in (1.12,1.13,1.14,1.15,1.16,1.17,1.18,1.20):
    line=f"   {t:6.3f} |"
    for mk in (X_,B_):
        m=mk&BASE&(~BAD)&(pq>t); n,h,r,im=roi(m)
        line+=f" {n:5,}点 {r:6.1f}% |"
    m=(X_|B_)&BASE&(~BAD)&(pq>t); n,h,r,im=roi(m); (lo,hi),pw=boot(m)
    line+=f" {n:5,}点 {r:6.1f}% [{lo:3.0f},{hi:3.0f}] P={pw:.2f}"
    rx=roi(X_&BASE&(~BAD)&(pq>t))[2]; rb=roi(B_&BASE&(~BAD)&(pq>t))[2]
    print(line+("  ◎" if rx>100 and rb>100 else ""))
print("\n   外している側（風>=3m かつ 波<3cm）の成績")
for t in (1.15,1.16):
    for lab,mk in (("探索",X_),("独立",B_)):
        m=mk&BASE&BAD&(pq>t); n,h,r,im=roi(m)
        print(f"     p/q>{t} {lab}: {n:4,}点 的中{h:3} 回収率 {r:6.1f}% "
              f"実測/市場 {im:.2f}")

print("\n\n#### 7. 風向（kfile の wind_dir）####")
print("   場ごとに向きの意味が違うので、探索期間で『良い向き』を決めて独立期間で試す")
ok_dir=wdir>=0
m0=BASE&ok_dir&(pq>1.16)
print("   まず風向単体（場をまたいで）")
for i,nm in enumerate(DIRS):
    line=f"     {nm:<4}|"
    for mk in (X_,B_):
        m=mk&m0&(wdir==i); n,h,r,im=roi(m)
        line+=f" {n:5,}点 {r:6.1f}% |" if n>=20 else f"{'(少)':>14}|"
    print(line)
print("\n   場×風向で探索期間の上位半分を選び、独立期間で試す")
cells={}
for j in np.unique(C["jcd"][BASE].astype(int)):
    for i in range(len(DIRS)):
        m=X_&m0&(C["jcd"]==j)&(wdir==i)
        if m.sum()>=25:
            cells[(j,i)]=roi(m)[2]
if cells:
    med=np.median(list(cells.values()))
    good={k for k,v in cells.items() if v>med}
    gm=np.zeros(len(A),bool)
    for (j,i) in good:
        gm |= (C["jcd"]==j)&(wdir==i)
    for lab,mk in (("探索(選んだ側)",X_),("独立(検証)",B_)):
        n,h,r,im=roi(mk&m0&gm); n2,h2,r2,_=roi(mk&m0&~gm)
        print(f"     {lab}: 良い向き {n:5,}点 {r:6.1f}% / "
              f"それ以外 {n2:5,}点 {r2:6.1f}%  差 {r-r2:+.1f}pt")
    print(f"     （{len(cells)}セル中 {len(good)}セルを『良い向き』とした）")

print("\n\n#### 8. 『風>=3m 波<3cm』は、しきい値を下げて数を増やしても悪いか ####")
print("   少数の偶然でないことを確かめる。帯の母集団（淡水以外）全体で見る")
print(f"   {'p/q>':>6} |{'除外する側(風>=3&波<3)':>34}|{'残す側':>34}")
for t in (1.00,1.05,1.097,1.12,1.16):
    line=f"   {t:6.3f} |"
    for sub in (BAD,~BAD):
        for mk in (X_,B_):
            m=mk&BASE&sub&(pq>t); n,h,r,im=roi(m)
            line+=f" {n:6,}点 {r:6.1f}%(実/市{im:4.2f})" if n else f"{'—':>16}"
        line+=" |"
    print(line)

print("\n\n#### 9. 風>=3m のとき、波はどこで切るのが良いか ####")
print(f"   {'波':>10} |{'探索':>16}|{'独立':>16}  (風>=3m・p/q>1.14)")
for lo_,hi_ in ((0,1),(1,2),(2,3),(3,4),(4,6),(6,10),(10,99)):
    line=f"   {lo_}〜{hi_}cm |"
    for mk in (X_,B_):
        m=mk&BASE&(C["wind"]>=3)&(C["wave"]>=lo_)&(C["wave"]<hi_)&(pq>1.14)
        n,h,r,im=roi(m)
        line+=f" {n:4,}点 {r:6.1f}% |" if n>=15 else f"{'(少)':>16}|"
    print(line)

print("\n\n#### 10. 候補の月別と金額（p/q>1.15 と 1.16）####")
ym=(d//100).astype(int); per=X_|B_
CAND={"風<4m":BASE&(C["wind"]<4),"風<3m":BASE&(C["wind"]<3),
      "風>=3&波<3を外す":BASE&(~BAD),"風の条件なし":BASE}
for t in (1.15,1.16):
    print(f"\n  --- p/q>{t} ---")
    print("    年月   " + "".join(f"{k:>16}" for k in CAND))
    cnt={k:0 for k in CAND}
    for y in np.unique(ym[per&BASE]):
        line=f"    {y} "
        for k,P in CAND.items():
            m=P&per&(ym==y)&(pq>t); n=int(m.sum())
            r=(hit[m]*od[m]*100).mean() if n else np.nan
            if n and r>100: cnt[k]+=1
            line+=f" {n:4,} {r:6.1f}%"
        print(line)
    print("    100%超の月: " + "".join(f"{cnt[k]:>16}" for k in CAND)+" /17")
    print("    金額(100円/点): " + "".join(
        f"{float((hit[P&per&(pq>t)]*od[P&per&(pq>t)]*100).sum())-int((P&per&(pq>t)).sum())*100:+15,.0f}円"
        for P in CAND.values()))

print("\n\n#### 11. 捨てている側（風が強いレース）は本当に悪いのか ####")
print(f"   {'':>12}|{'探索 2026/02-09':>28}|{'独立 2025/05-2026/01':>28}")
for cut in (3,4,5):
    for t in (1.12,1.15,1.16):
        line=f"   風>={cut}m p/q>{t} |"
        for mk in (X_,B_):
            m=mk&BASE&(C["wind"]>=cut)&(pq>t); n,h,r,im=roi(m)
            line+=f" {n:5,}点 的中{h:3} {r:6.1f}% 実/市{im:4.2f} |"
        print(line)
    print()

print("\n#### 12. 点数を揃えると、風の足切りに意味は残るか ####")
print("   同じ点数を買ったときの回収率。風で絞る vs 絞らず p/q を上げる")
for mk,lab in ((X_,"探索 2026/02-09"),(B_,"独立 2025/05-2026/01")):
    print(f"\n   --- {lab} ---")
    print(f"     {'点数':>6} |" + "".join(f"{k:>22}|" for k in
          ("風<3m","風<4m","風<5m","風の条件なし")))
    for N in (400,600,800,1000,1200,1600):
        line=f"     {N:6,} |"
        for cut in (3,4,5,99):
            idx=np.where(mk&BASE&(C["wind"]<cut))[0]
            if len(idx)<N: line+=f"{'—':>22}|"; continue
            s=idx[np.argsort(-pq[idx])[:N]]
            line+=(f" p/q>{pq[s].min():5.3f} {(hit[s]*od[s]*100).mean():6.1f}%|")
        print(line)
