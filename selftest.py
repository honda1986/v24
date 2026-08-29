#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest.py -- ネットに出ずに、計算の筋道だけを確かめる

  出走表 → 特徴量 → モデル → 1着確率 → 3連単120通り → 買い目
の形が通るかを見る。デプロイ後にまずこれを叩くと、
「モデルの特徴量がずれている」「買い目が0点になる」といった事故が先に分かる。
"""
import json
import os
import sys

import numpy as np

import features as F
import select_rule as SR


def fake_race(seed=0, favorite=1.0):
    rng = np.random.default_rng(seed)
    # 本命に厚い3連単オッズを作る(実際の形に近づける)
    w = rng.dirichlet(np.ones(120) * 0.25)
    w[F.FIRST == 0] *= 6.0 * favorite          # 1号艇を厚く
    w = w / w.sum()
    odds = np.round(0.748 / np.maximum(w, 1e-6), 1)
    lanes = []
    for i in range(6):
        lanes.append({
            "lane": i + 1, "cls_val": int(rng.integers(1, 5)),
            "age": 30.0, "weight": 52.0 + rng.normal(0, 2),
            "f_count": 0.0, "avg_st": 0.16, "n_win": 5.0 + rng.normal(0, 1),
            "n_2ren": 0.30, "l_win": 5.0, "l_2ren": 0.30,
            "m_2ren": 0.35, "b_2ren": 0.35, "tok": 6.0, "srank": 10,
            "genten": 0.0, "nruns": 4, "st_setsu": 0.16, "c_win": 20.0,
            "c_ren3": 40.0, "c_st": 0.16, "tenji": 6.75 + rng.normal(0, 0.05),
            "mot_pure": float(rng.normal(0, 0.02)),
        })
    meta = {"jcd": 24, "rno": 5, "day_no": 3, "n_days": 6, "is_final": 0}
    return lanes, meta, odds


def main():
    ok = True
    print("1) 特徴量")
    lanes, meta, odds = fake_race(0)
    q, q1 = F.market_probs(odds)
    assert q is not None, "オッズから市場確率が作れない"
    X = F.build_race(lanes, meta, q1)
    print(f"   形 {X.shape}  期待 (6, {len(F.FEATS)})")
    ok &= X.shape == (6, len(F.FEATS))
    print(f"   市場の1号艇1着確率 {q1[0]:.3f}  帯に入る組 "
          f"{int(((q >= SR.Q_LO) & (q < SR.Q_HI)).sum())}点")

    print("\n2) 保存されているモデルとの整合")
    fp = "model/features.json"
    if os.path.exists(fp):
        saved = json.load(open(fp, encoding="utf-8"))
        same = saved == F.FEATS
        print(f"   model/features.json と features.py: {'一致' if same else '★不一致'}")
        ok &= same
    else:
        print("   model/features.json がまだありません(train.py 未実行)")

    print("\n3) 3連単への展開と買い目")
    # モデルの代わりに「市場を少しだけ歪めたもの」を使う
    for tag, tweak in (("市場どおり", np.ones(6)),
                       ("1号艇を1.15倍に見る", np.array([1.15, 1, 1, 1, 1, 1])),
                       ("2号艇を1.30倍に見る", np.array([1, 1.30, 1, 1, 1, 1]))):
        p1 = q1 * tweak; p1 = p1 / p1.sum()
        cp = F.trifecta(p1, q)
        buy = SR.pick(q, cp)
        s = abs(cp.sum() - 1.0)
        ok &= s < 1e-9
        print(f"   {tag:<22} 合計{cp.sum():.6f}  買い目 {len(buy)}点"
              + ("  " + " ".join(F.COMBOS[i] for i in buy[:4]) if buy else ""))

    print("\n4) レースの足切り")
    cases = [(24, 1, 2, True, "大村・波1cm・風2m"),
             (2, 1, 2, False, "戸田(淡水)"),
             (24, 6, 2, False, "波6cm"),
             (24, 1, 5, False, "風5m"),
             (24, None, 2, False, "気象が取れない")]
    for jcd, wv, wd, want, nm in cases:
        got = SR.race_ok(jcd, wv, wd)
        ok &= got == want
        print(f"   {nm:<22} {'買う' if got else '見送り'}"
              + ("" if got == want else "  ★期待と違う"))

    print("\n" + ("すべて通りました" if ok else "★失敗があります"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
