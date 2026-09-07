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
import select_rule as SR      # noqa: E402

SEC_IDX = np.array([int(c[2]) - 1 for c in F.COMBOS])
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
    print(f"2着の補正 {'あり' if m2 is not None else 'なし'}")

    races = collect(args)
    print(f"\n買える条件のレース {len(races):,}（{args.frm} 以降）")
    rows = {False: [], True: []}
    for d, lanes, mt, od, q, q1, hit in races:
        X = F.build_race(lanes, mt, q1)
        raw = np.asarray(m1.predict(X), dtype=float)
        p1 = raw / raw.sum()
        base = F.trifecta(p1, q)
        g = (S.gmatrix(m2, lanes, mt, q, F.FIRST, SEC_IDX)
             if m2 is not None else None)
        for useg in ([False, True] if m2 is not None else [False]):
            cp = base * (g[F.FIRST, SEC_IDX] if useg else 1.0)
            cp = cp / cp.sum()
            for i in np.where((q >= SR.Q_LO) & (q < SR.Q_HI))[0]:
                rows[useg].append((cp[i] / q[i], q[i], od[i],
                                   1.0 if i == hit else 0.0, d))

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

    A0 = np.array(rows[False])
    n_now = int((A0[:, 0] > SR.PQ_MIN).sum())
    print(f"\nいまのしきい値 {SR.PQ_MIN} で買う点数: {n_now:,}")
    ns = sorted({800, 1200, n_now, 2200, 2800})
    report(A0, "g なし（いまの本番）", ns)
    if m2 is not None:
        A1 = np.array(rows[True])
        report(A1, "★g あり（2着の補正）", ns)
        th = np.quantile(A1[:, 0], 1 - n_now / len(A1))
        print(f"\n  点数を {n_now:,} に揃えるしきい値: {th:.4f}"
              f"（select_rule.PQ_MIN_G は {SR.PQ_MIN_G}）")
    print(f"\n★収支トントンに必要な 実測/市場 は 1.337")
    print("  誤差(±)を見ること。100%を1回超えただけでは超えたことにならない")


if __name__ == "__main__":
    main()
