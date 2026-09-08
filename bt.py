#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bt.py -- 学習に使っていない期間で回収率を測る（本番のモデルで）

★これまで回収率は開発用の代役モデルでしか測っていなかった。
  本番の LightGBM で確かめられる手段が無いのは危ない。これはその補完。

  python bt.py --raw v22/raw --tokuten v22/tokuten --pure /content/pure.npz \\
      --kfile v22/kfile --model model --from 20250401

2着の補正 g がある場合は「g なし / g あり」を**同じ買い目点数で**比べる。
点数が違うと比較にならない（g は p/q を押し上げるので点数が増える）。
"""
import argparse
import glob
import gzip
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F          # noqa: E402
import second as S            # noqa: E402
import third as T             # noqa: E402
import select_rule as SR      # noqa: E402

SEC_IDX = np.array([int(c[2]) - 1 for c in F.COMBOS])
THI_IDX = np.array([int(c[4]) - 1 for c in F.COMBOS])
BET = 100


def collect(args):
    p = np.load(args.pure, allow_pickle=True)
    cols = list(p["cols"])
    pk = p["date"].astype(np.int64) * 100000 + p["toban"]
    po = np.argsort(pk); pk = pk[po]
    pv = p["vals"][po][:, cols.index("mot_pure")]
    kw = {}
    for path in sorted(glob.glob(f"{args.kfile}/*.json.gz")):
        d = int(os.path.basename(path)[:8])
        if d < args.frm:
            continue
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for r in json.load(f)["races"]:
                kw[(d, r["jcd"], r["rno"])] = (r.get("wave"), r.get("wind"))
    print(f"kfile {len(kw):,}レース", flush=True)
    tokf = {os.path.basename(x)[:8]: x for x in glob.glob(f"{args.tokuten}/*.json.gz")}
    out = []
    rawf = [x for x in sorted(glob.glob(f"{args.raw}/*.json.gz"))
            if int(os.path.basename(x)[:8]) >= args.frm]
    t0 = time.time()
    for k, path in enumerate(rawf):
        d = os.path.basename(path)[:8]
        with gzip.open(path, "rt", encoding="utf-8") as f:
            rd = json.load(f)
        tk, meta = {}, {}
        if d in tokf:
            with gzip.open(tokf[d], "rt", encoding="utf-8") as f:
                td = json.load(f)
            for js, v in (td.get("venues") or {}).items():
                j = int(js)
                for r in v.get("races", []):
                    meta[(j, r["rno"])] = (r.get("name", ""), v.get("day_no"),
                                           v.get("n_days"))
                    for x in r["lanes"]:
                        tk[(j, r["rno"], x["lane"])] = x
        for r in rd["races"]:
            if "error" in r or not r.get("hit") or len(r.get("entries", [])) != 6:
                continue
            od = r.get("odds") or []
            if len(od) != 120 or not all(o and o > 0 for o in od):
                continue
            if r["hit"] not in F.CIX:
                continue
            wave, wind = kw.get((int(d), r["jcd"], r["rno"]), (None, None))
            if not SR.race_ok(r["jcd"], wave, wind):
                continue
            q, q1 = F.market_probs(od)
            if q is None:
                continue
            nm, day_no, n_days = meta.get((r["jcd"], r["rno"]), ("", None, None))
            lanes = []
            for e in sorted(r["entries"], key=lambda z: z["lane"]):
                x = tk.get((r["jcd"], r["rno"], e["lane"]), {})
                tb = x.get("toban"); mp = np.nan
                if tb:
                    key = int(d) * 100000 + int(tb)
                    i = np.searchsorted(pk, key)
                    if i < len(pk) and pk[i] == key:
                        mp = float(pv[i])
                tj = e.get("tenji")
                lanes.append({
                    "lane": e["lane"], "cls_val": e.get("cls_val"),
                    "age": e.get("age"), "weight": e.get("weight"),
                    "f_count": e.get("f_count"), "avg_st": e.get("avg_st"),
                    "n_win": e.get("n_win"), "n_2ren": e.get("n_2ren"),
                    "l_win": e.get("l_win"), "l_2ren": e.get("l_2ren"),
                    "m_2ren": e.get("m_2ren"), "b_2ren": e.get("b_2ren"),
                    "tok": x.get("tokuten"), "srank": x.get("rank"),
                    "genten": x.get("genten"), "nruns": x.get("n_runs"),
                    "st_setsu": x.get("st_setsu"), "c_win": x.get("c_win"),
                    "c_ren3": x.get("c_ren3"), "c_st": x.get("c_st"),
                    "tenji": tj if tj and tj > 0 else None,
                    "mot_pure": None if np.isnan(mp) else mp})
            mt = {"jcd": r["jcd"], "rno": r["rno"], "day_no": day_no,
                  "n_days": n_days, "wave": wave, "wind": wind,
                  "is_final": 1 if any(w in (nm or "")
                                       for w in ("準優", "優勝", "選抜")) else 0}
            out.append((int(d), lanes, mt, np.asarray(od, float), q, q1,
                        F.CIX[r["hit"]]))
        if (k + 1) % 100 == 0:
            print(f"  {k+1}/{len(rawf)}日  {len(out):,}レース  "
                  f"{time.time()-t0:.0f}秒", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="v22/raw")
    ap.add_argument("--tokuten", default="v22/tokuten")
    ap.add_argument("--pure", default="pure.npz")
    ap.add_argument("--kfile", default="v22/kfile")
    ap.add_argument("--model", default="model")
    ap.add_argument("--from", dest="frm", type=int, default=20250401)
    args = ap.parse_args()
    import lightgbm as lgb

    with open(f"{args.model}/features.json", encoding="utf-8") as f:
        if json.load(f) != F.FEATS:
            sys.exit("★モデルの特徴量が features.py と食い違っています")
    m1 = lgb.Booster(model_file=f"{args.model}/lgb_mf.txt")
    m2 = S.load(args.model)
    m3 = T.load(args.model)
    print(f"2着の補正 {'あり' if m2 is not None else 'なし'} / "
          f"3着の補正 {'あり' if m3 is not None else 'なし'}")

    races = collect(args)
    print(f"\n買える条件のレース {len(races):,}（{args.frm} 以降）")
    names = ["base"] + (["g"] if m2 is not None else []) \
        + (["g+h"] if (m2 is not None and m3 is not None) else
           (["h"] if m3 is not None else []))
    rows = {k: [] for k in names}
    for rno_, (d, lanes, mt, od, q, q1, hit) in enumerate(races):
        X = F.build_race(lanes, mt, q1)
        raw = np.asarray(m1.predict(X), dtype=float)
        p1 = raw / raw.sum()
        base = F.trifecta(p1, q)
        gv = (S.gmatrix(m2, lanes, mt, q, F.FIRST, SEC_IDX)[F.FIRST, SEC_IDX]
              if m2 is not None else 1.0)
        hv = (T.hvector(m3, lanes, mt, q, F.FIRST, SEC_IDX, THI_IDX)
              if m3 is not None else 1.0)
        var = {"base": base}
        if "g" in names:
            var["g"] = base * gv
        if "g+h" in names:
            var["g+h"] = base * gv * hv
        if "h" in names:
            var["h"] = base * hv
        for k, cp in var.items():
            cp = cp / cp.sum()
            for i in np.where((q >= SR.Q_LO) & (q < SR.Q_HI))[0]:
                rows[k].append((cp[i] / q[i], q[i], od[i],
                                1.0 if i == hit else 0.0, d, rno_, i))

    def report(A, lab, ns):
        pq, qq, od, hh, dd = (A[:, i] for i in range(5))
        o = np.argsort(-pq); half = np.median(dd)
        print(f"\n【{lab}】帯に入った {len(A):,}組。p/q の高い順に買った場合")
        for nb in ns:
            if nb > len(A):
                continue
            s = o[:nb]
            # 1点100円。払戻はオッズ×100円。r は「賭けた100円あたりの戻り(%)」
            r = hh[s] * od[s] * 100.0
            h1 = dd[s] < half
            print(f"  上位{nb:5,}点  回収率 {r.mean():6.1f}% "
                  f"±{r.std(ddof=1)/np.sqrt(nb):4.1f}  "
                  f"実測/市場 {hh[s].sum()/qq[s].sum():.3f}   "
                  f"前半 {r[h1].mean() if h1.any() else 0:.1f}% / "
                  f"後半 {r[~h1].mean() if (~h1).any() else 0:.1f}%")

    def paired(A0, A1, nb):
        """★同じレースを両方が買っているので、別々の誤差で比べてはいけない。
        重なっている組は差に効かない。入れ替わった分だけを見て、
        レース単位でブートストラップする（同じレースの組は一緒に揺れる）。
        """
        def key(A, nb):
            s = np.argsort(-A[:, 0])[:nb]
            return set(zip(A[s, 5].astype(int).tolist(),
                           A[s, 6].astype(int).tolist())), s
        k0, s0 = key(A0, nb)
        k1, s1 = key(A1, nb)
        m0 = np.array([(int(a), int(b)) in (k0 - k1)
                       for a, b in zip(A0[s0, 5], A0[s0, 6])])
        m1 = np.array([(int(a), int(b)) in (k1 - k0)
                       for a, b in zip(A1[s1, 5], A1[s1, 6])])
        o0, o1 = A0[s0][m0], A1[s1][m1]
        if len(o0) == 0 or len(o1) == 0:
            return None
        def ret(a):
            return a[:, 2] * a[:, 3] * 100.0          # 100円あたりの戻り(%)
        d = (ret(o1).sum() - ret(o0).sum()) / nb
        rng = np.random.default_rng(0)
        r0, r1 = o0[:, 5].astype(int), o1[:, 5].astype(int)
        allr = np.unique(np.concatenate([r0, r1]))
        idx = {v: i for i, v in enumerate(allr)}
        i0 = np.array([idx[v] for v in r0]); i1 = np.array([idx[v] for v in r1])
        boot = np.empty(2000)
        for t in range(2000):
            w = np.bincount(rng.integers(0, len(allr), len(allr)),
                            minlength=len(allr))
            boot[t] = ((ret(o1) * w[i1]).sum() - (ret(o0) * w[i0]).sum()) / nb
        return d, boot.std(ddof=1), float((boot > 0).mean()), len(o0), len(o1)

    AR = {k: np.array(v) for k, v in rows.items()}
    A0 = AR["base"]
    n_now = int((A0[:, 0] > SR.PQ_MIN).sum())
    print(f"\nいまのしきい値 {SR.PQ_MIN} で買う点数: {n_now:,}")
    ns = sorted({800, 1200, n_now, 2200, 2800})
    LAB = {"base": "補正なし（従来）", "g": "2着の補正のみ",
           "h": "3着の補正のみ", "g+h": "★2着＋3着の補正"}
    for k in names:
        report(AR[k], LAB[k], ns)
    for k in names[1:]:
        th = np.quantile(AR[k][:, 0], 1 - n_now / len(AR[k]))
        print(f"\n  【{LAB[k]}】点数を {n_now:,} に揃えるしきい値: {th:.4f}")
    print("\n★同じ点数での「差」（重なりを除いて日単位ブートストラップ）")
    pairs_to_test = [(a, b) for a, b in
                     (("base", "g"), ("g", "g+h"), ("base", "g+h"),
                      ("base", "h")) if a in names and b in names]
    for a, b in pairs_to_test:
        print(f"  【{LAB[b]} − {LAB[a]}】")
        for nb in ns:
            if nb > min(len(AR[a]), len(AR[b])):
                continue
            r = paired(AR[a], AR[b], nb)
            if r is None:
                continue
            d, sd, pr, c0, c1 = r
            print(f"    {nb:6,}点  {d:+7.1f}pt ±{sd:4.1f}  "
                  f"正の確率 {pr*100:3.0f}%   入替え{c0}点")
    print("  ※ 重なっている組は差に効かない。入替えの分だけで判定している")
    print(f"\n★収支トントンに必要な 実測/市場 は 1.337")
    print("  誤差(±)を見ること。100%を1回超えただけでは超えたことにならない")


if __name__ == "__main__":
    main()
