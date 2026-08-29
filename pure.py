# -*- coding: utf-8 -*-
"""pure.py -- Kファイルから「交絡を除いた」特徴量を日次で作る(バックテスト用)

appV23/motor.py は最終日のスナップショットしか作らないので、
バックテストに使える日次の時系列版がどこにも無かった。これはその補完。

日 D の値は 日 D 未満のKファイルだけから作る(当日ぶんは使わない)。
motor.py と同じ「レース内偏差 - 本人の平常値」の形をすべての候補で踏襲する。

出力: work/pure.npz  (date, toban, 各特徴量)

  mot_pure   展示タイムのモーター純度。motor.py の再現(検算用)
  m2_recent  モーターの直近2連率(素)。★対照群。
             「効いたのは交絡除去か、それとも単に新しい数字だからか」を分ける
  m2_pure    モーター2連率から選手要因と枠要因を除いたもの
  b2_pure    ボート2連率から同上
  st_pure    平均STから場・コースの交絡を除いたもの(大きいほど速い)
  win_pure   1着率から場・コースの交絡を除いたもの

窓と最低走数は先に決めて動かさない(§3「閾値の探索はノイズを掴みやすい」)。
"""
import argparse
import datetime
import glob
import gzip
import json
import os
from collections import defaultdict, deque

import numpy as np

# --- 展示(motor.py と同じ) -------------------------------------------
TJ_MOT, TJ_MIN, TJ_RAC = 10, 5, 100
# --- 2連率系。印刷される m_2ren は年度累計(60〜100走規模)なので窓もそこに合わせる。
#     こうすれば「窓の長さ」ではなく「交絡を除いたかどうか」だけが差になる
R2_MOT, R2_MIN, R2_RAC = 60, 20, 100
# --- ST・1着率(選手側)。節をまたいで安定させたいので30走
RC_LEN, RC_MIN = 30, 10
SEEN_DAYS = 7            # これより前にしか走っていない選手は節が変わっている
CS_MIN = 200             # 場×コースの基準値を使い始める最低本数

_W = {}


def wavg(a):
    """直近重み付き平均(0.5→1.5の線形)。motor.py と同じ"""
    n = len(a)
    w = _W.get(n)
    if w is None:
        w = np.linspace(0.5, 1.5, n)
        w /= w.sum()
        _W[n] = w
    return float(np.dot(a, w))


def dwavg(dq, need):
    if dq is None or len(dq) < need:
        return np.nan
    return wavg(np.fromiter(dq, np.float64, len(dq)))


def iter_days(kdir):
    for p in sorted(glob.glob(f"{kdir}/*.json.gz")):
        d = os.path.basename(p)[:8]
        with gzip.open(p, "rt", encoding="utf-8") as f:
            kd = json.load(f)
        races = []
        for r in kd.get("races") or []:
            es = r.get("entries") or []
            if len(es) != 6:
                continue
            lane = [e.get("lane", 0) for e in es]
            if sorted(lane) != [1, 2, 3, 4, 5, 6]:
                continue
            o = np.argsort(lane)
            races.append((int(r["jcd"]), [es[i] for i in o]))
        yield d, races


def to_ord(d):
    return datetime.date(int(d[:4]), int(d[4:6]), int(d[6:8])).toordinal()


def chaku_of(e):
    c = str(e.get("chaku") or "")
    return int(c) if c.isdigit() and 1 <= int(c) <= 6 else None


class State:
    def __init__(self):
        self.tj_mot = defaultdict(lambda: deque(maxlen=TJ_MOT))
        self.tj_rac = defaultdict(lambda: deque(maxlen=TJ_RAC))
        self.r2_mot = defaultdict(lambda: deque(maxlen=R2_MOT))
        self.r2_raw = defaultdict(lambda: deque(maxlen=R2_MOT))
        self.r2_boat = defaultdict(lambda: deque(maxlen=R2_MOT))
        self.r2_rac = defaultdict(lambda: deque(maxlen=R2_RAC))
        self.lane_n = np.zeros(7)
        self.lane_s = np.zeros(7)
        self.cs_n = defaultdict(float)      # 場×コースの本数(着順用)
        self.cs_win = defaultdict(float)
        self.cs_stn = defaultdict(float)    # 場×コースの本数(ST用)
        self.cs_st = defaultdict(float)
        self.st_rac = defaultdict(lambda: deque(maxlen=RC_LEN))
        self.win_rac = defaultdict(lambda: deque(maxlen=RC_LEN))
        self.seen = {}                      # toban -> (ord, jcd, motor, boat)

    def snapshot(self, dord, date_i):
        lim = dord - SEEN_DAYS
        rows = []
        for t, (o, jcd, mt, bt) in self.seen.items():
            if not t or o < lim:
                continue
            rows.append((date_i, t,
                         dwavg(self.tj_mot.get((jcd, mt)), TJ_MIN),
                         dwavg(self.r2_raw.get((jcd, mt)), R2_MIN),
                         dwavg(self.r2_mot.get((jcd, mt)), R2_MIN),
                         dwavg(self.r2_boat.get((jcd, bt)), R2_MIN),
                         dwavg(self.st_rac.get(t), RC_MIN),
                         dwavg(self.win_rac.get(t), RC_MIN)))
        return rows

    def ingest(self, dord, races):
        for jcd, es in races:
            tj = np.array([e.get("tenji") or np.nan for e in es], float)
            tj[tj <= 0] = np.nan
            with np.errstate(invalid="ignore"):
                dev = tj - np.nanmean(tj)
            for j, e in enumerate(es):
                t = e.get("toban") or 0
                mt = e.get("motor") or 0
                bt = e.get("boat") or 0
                lane = e.get("lane") or 0
                self.seen[t] = (dord, jcd, mt, bt)

                # --- 展示(motor.py と同一) ---
                v = dev[j]
                if not np.isnan(v):
                    rq = self.tj_rac[t]
                    base = float(np.mean(rq)) if len(rq) >= 5 else 0.0
                    self.tj_mot[(jcd, mt)].append(v - base)
                    rq.append(v)

                c = chaku_of(e)
                if c is None:
                    continue
                is2 = 1.0 if c <= 2 else 0.0
                is1 = 1.0 if c == 1 else 0.0

                # --- 2連率。枠の平均を引いてから、選手の平常値を引く ---
                if self.lane_n[lane] >= 500:
                    d2 = is2 - self.lane_s[lane] / self.lane_n[lane]
                    self.r2_raw[(jcd, mt)].append(is2)
                    rq = self.r2_rac[t]
                    if len(rq) >= 20:
                        rb = float(np.mean(rq))
                        self.r2_mot[(jcd, mt)].append(d2 - rb)
                        self.r2_boat[(jcd, bt)].append(d2 - rb)
                    rq.append(d2)
                self.lane_n[lane] += 1
                self.lane_s[lane] += is2

                # --- ST・1着率。場×コースの基準を引く ---
                co = e.get("course") or 0
                if 1 <= co <= 6:
                    key = (jcd, co)
                    if self.cs_n[key] >= CS_MIN:
                        self.win_rac[t].append(is1 - self.cs_win[key] / self.cs_n[key])
                    self.cs_n[key] += 1
                    self.cs_win[key] += is1
                    st = e.get("st")
                    if st is not None and not e.get("st_flag"):
                        st = float(st)
                        if self.cs_stn[key] >= CS_MIN:
                            # 符号を反転。大きいほど速い
                            self.st_rac[t].append(self.cs_st[key] / self.cs_stn[key] - st)
                        self.cs_stn[key] += 1
                        self.cs_st[key] += st


COLS = ["mot_pure", "m2_recent", "m2_pure", "b2_pure", "st_pure", "win_pure"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kfile", default="/root/v22/kfile")
    ap.add_argument("--out", default="/root/work/pure.npz")
    args = ap.parse_args()

    st = State()
    out, nd = [], 0
    for d, races in iter_days(args.kfile):
        out.extend(st.snapshot(to_ord(d), int(d)))
        st.ingest(to_ord(d), races)
        nd += 1
        if nd % 100 == 0:
            print(f"  {nd}日  {d}  {len(out):,}行", flush=True)

    a = np.array(out, dtype=np.float64)
    print(f"完了 {nd}日 / {len(a):,}行")
    np.savez_compressed(args.out, date=a[:, 0].astype(np.int32),
                        toban=a[:, 1].astype(np.int32),
                        vals=a[:, 2:].astype(np.float32),
                        cols=np.array(COLS))
    for i, c in enumerate(COLS):
        v = a[:, 2 + i]
        print(f"  {c:<10} 欠損{100*np.isnan(v).mean():5.1f}%  "
              f"平均{np.nanmean(v):+.4f} 標準偏差{np.nanstd(v):.4f}")


if __name__ == "__main__":
    main()
