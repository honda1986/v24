#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yosou.py -- v24 の本体。10分ごとに動き、締切30分以内のレースだけ処理する。

■ v23 との決定的な違い
  オッズがモデルの入力になった。だから朝にまとめて予想して通知を予約する形は使えない。
  展示が出て(締切30〜40分前)、オッズが動いてから予想する。

■ 1回の実行でやること
  1. 淡水9場は最初から見ない            → リクエスト0
  2. 締切まで 4〜30分 のレースを拾う      → 締切時刻は1日1回だけ取ってキャッシュ
  3. 直前情報を取り、波・風で足切り       → 落ちればオッズを取らない
  4. オッズを取り、予想して買い目を決める
  5. 買い目があれば ntfy に即時通知し、通知済みとして記録する

■ 足切りの順番が大事
  淡水(場番だけで分かる) → 波・風(1リクエスト) → オッズ(1リクエスト)
  この順にすると、10分の実行時間に収まる。逆にすると間に合わない。

■ ログの読み方
  「特徴量 57個」でなければモデルが古い
  「モーター純度 …人」が出ていなければ motor.py が走っていない → 異常終了する
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

import numpy as np

import features as F
import official as OF
import beforeinfo as BI
import racecard as RC
import select_rule as SR
import tokuten as TK          # v23 から流用(無改造)

SITE = "history.json"      # 予想サイト(index.html)が読む
MODEL_DIR = "model"
CACHE_DIR = "cache"
STATE_DIR = "state"
WIN_HI = 30        # 締切まで何分以内を対象にするか
WIN_LO = 4         # これより締切が近いレースは投票が間に合わないので見送る
BET_YEN = 100      # 1点あたりの賭け金
VENUE = {1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖",
         7: "蒲郡", 8: "常滑", 9: "津", 10: "三国", 11: "びわこ", 12: "住之江",
         13: "尼崎", 14: "鳴門", 15: "丸亀", 16: "児島", 17: "宮島", 18: "徳山",
         19: "下関", 20: "若松", 21: "芦屋", 22: "福岡", 23: "唐津", 24: "大村"}


# ---------------------------------------------------------------- 入出力
def _load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def prune(date):
    """当日ぶん以外のキャッシュと通知記録を消す。

    cache/ はリポジトリに残す(10分ごとの実行で締切時刻と出走表を取り直さないため)。
    残しっぱなしだと膨らむので、日付が変わったら古いぶんを捨てる。
    """
    for d, pat in ((CACHE_DIR, ("close_", "card_", "rc_")),
                   (STATE_DIR, ("notified_",))):
        for name in os.listdir(d) if os.path.isdir(d) else []:
            if name.startswith(pat) and date not in name:
                try:
                    os.remove(f"{d}/{name}")
                except OSError:
                    pass


def load_model():
    import lightgbm as lgb
    feats = _load(f"{MODEL_DIR}/features.json")
    if feats is None:
        sys.exit(f"{MODEL_DIR}/features.json がありません。train.py で作ってください")
    if feats != F.FEATS:
        sys.exit("★モデルの特徴量が features.py と食い違っています。"
                 f"モデル{len(feats)}個 / いま{len(F.FEATS)}個。学習し直してください")
    print(f"{datetime.now(OF.JST):%Y%m%d} の予想を作ります (特徴量 {len(feats)}個)")
    return lgb.Booster(model_file=f"{MODEL_DIR}/lgb_mf.txt")


def load_motor(path="motor/latest.json"):
    """モーター純度。無ければ異常終了する。

    v23 では取れなくても予想が出てしまい、気づけなかった(メモ §1)。v24 では落とす。
    """
    j = _load(path)
    v = {str(k): float(x) for k, x in ((j or {}).get("values") or {}).items()}
    if not v:
        sys.exit("★モーター純度が取れません。motor.py が走っていません")
    d = str(j.get("date") or "")
    today = datetime.now(OF.JST).date()
    try:
        age = (today - datetime.strptime(d, "%Y%m%d").date()).days
    except ValueError:
        sys.exit(f"★モーター純度の日付が読めません: {d!r}")
    # ★古い純度は「欠測」ではなく「間違った数字」になる。mot_pure は登録番号で
    #   引くが、節が変われば同じ選手が別のモーターに乗る（motor.py は直近7日で
    #   絞っている）。日付を見ないと、壊れたまま静かに動き続ける。
    if age > 3:
        sys.exit(f"★モーター純度が古すぎます（{d}、{age}日前）。motor.py を直すこと")
    print(f"モーター純度 {d} {len(v):,}人（{age}日前）")
    return v


# ---------------------------------------------------------------- 締切時刻
def close_times(date, jcds, deadline=None):
    """締切予定時刻。日中は変わらないので1日1回だけ取る。

    ★1場8〜10秒かかるので15場で150秒。ここだけで持ち時間を食い尽くす。
      1場取るごとに保存し、途中で打ち切っても次の回が続きから進めるようにする。
      （まとめて最後に保存する作りだと、ジョブが落ちた回はまるごと無駄になる）
    """
    path = f"{CACHE_DIR}/close_{date}.json"
    cache = _load(path, {}) or {}
    need = [j for j in jcds if str(j) not in cache]
    if need:
        print(f"締切時刻を取ります {len(need)}場", flush=True)
        for k, j in enumerate(need):
            if deadline and time.time() > deadline:
                print(f"  持ち時間が尽きたので{len(need)-k}場は次の回へ", flush=True)
                break
            times, settled = OF.fetch_close(date, j)
            if not settled:             # 通信失敗。次の回に取り直す
                print(f"  {j:02d}場 締切時刻が取れず。次の回へ", flush=True)
                continue
            cache[str(j)] = times
            _save(path, cache)          # 1場ごとに残す
            time.sleep(0.4)
    return {int(k): v for k, v in cache.items() if v}


def card(date, jcd):
    """出走表と今節成績。1日1回だけ取る"""
    path = f"{CACHE_DIR}/card_{date}_{jcd:02d}.json"
    c = _load(path)
    if c is not None:
        return c
    html = TK.fetch(TK.make_session(), jcd, date)
    if not html:
        return None
    page = TK.parse_page(html, date)
    if not page or not page.get("races") or page.get("day_no") is None:
        return None
    page["jcd"] = jcd          # parse_page は jcd を持たないので入れておく
    _save(path, page)
    return page


def site_log(date, place, jcd, rno, close, buys, cp, q, odds, wave, wind, skipped,
             lanes=None, p1=None, q1=None, nmot=None):
    """index.html が読む history.json に、この回の結果を足す。

    ★1レース通知するたびに書いて commit する。まとめて最後に書くと、
      途中で落ちた回のぶんが残らない（state と同じ理由）。
    """
    h = _load(SITE, {}) or {}
    days = h.get("days") or []
    day = next((d for d in days if d["date"] == date), None)
    if day is None:
        day = {"date": date, "picks": [], "skipped": {}}
        days.append(day)
    for k, v in (skipped or {}).items():
        day["skipped"][k] = day["skipped"].get(k, 0) + v
    if buys:
        key = f"{jcd}-{rno}"
        if not any(p["jcd"] == jcd and p["rno"] == rno for p in day["picks"]):
            day["picks"].append({
                "jcd": jcd, "place": place, "rno": rno, "close": close,
                "wave": None if wave is None else round(float(wave)),
                "wind": None if wind is None else round(float(wind)),
                "buys": [{"combo": F.COMBOS[i], "q": round(float(q[i]), 5),
                          "p": round(float(cp[i]), 5),
                          "pq": round(float(cp[i] / q[i]), 3),
                          "odds": round(float(odds[i]), 1)} for i in buys],
                "cost": len(buys) * BET_YEN, "nmot": nmot,
                "combo": None, "pay": None, "hit": None, "ret": None,
                # 6艇の内訳。予想サイトで開いて中身を見るため
                "lanes": [{
                    "lane": x["lane"],
                    "name": x.get("name") or "",
                    "cls": x.get("cls_val"),
                    "n_win": x.get("n_win"),
                    "m_2ren": x.get("m_2ren"),
                    "tenji": x.get("tenji"),
                    "f": x.get("f_count"),
                    "st": x.get("avg_st"),
                    "tok": x.get("tok"),
                    "mot": (None if x.get("mot_pure") is None
                            else round(float(x["mot_pure"]), 4)),
                    "p": round(float(p1[i]), 4) if p1 is not None else None,
                    "q": round(float(q1[i]), 4) if q1 is not None else None,
                } for i, x in enumerate(sorted(lanes or [],
                                              key=lambda z: z["lane"]))],
            })
    h["days"] = sorted(days, key=lambda d: d["date"])
    h["updated"] = datetime.now(OF.JST).isoformat(timespec="seconds")
    _save(SITE, h)


KEEP_DETAIL_DAYS = 14      # 全レースの内訳を残す日数（履歴が膨らむので）


def site_race(date, place, jcd, rno, close, status, wave, wind,
              lanes=None, p1=None, q1=None, npt=0, nmot=None):
    """見たレースを全部残す（買い目が出なかったものも）。

    ★波・風で切ったレースはオッズを取っていないので、モデルの確率が無い。
      その場合は理由と気象だけ。これは仕組み上の限界で、全レースで
      モデルを回すには全レースのオッズが要り、10分に収まらない。
    """
    h = _load(SITE, {}) or {}
    days = h.get("days") or []
    day = next((d for d in days if d["date"] == date), None)
    if day is None:
        day = {"date": date, "picks": [], "skipped": {}}
        days.append(day)
    races = day.setdefault("races", [])
    rec = {"jcd": jcd, "place": place, "rno": rno, "close": close,
           "status": status,
           # 何艇にモーター純度が付いたか。節初日は少ない。
           # ガードを外した(§23)ので、あとで「少ない回は成績が違ったか」を
           # 検算できるように残しておく
           "nmot": nmot,
           "wave": None if wave is None else round(float(wave)),
           "wind": None if wind is None else round(float(wind)),
           "npt": npt}
    if lanes and p1 is not None and q1 is not None:
        rec["lanes"] = [{
            "lane": x["lane"], "name": x.get("name") or "",
            "cls": x.get("cls_val"), "n_win": x.get("n_win"),
            "m_2ren": x.get("m_2ren"), "tenji": x.get("tenji"),
            "f": x.get("f_count"), "st": x.get("avg_st"), "tok": x.get("tok"),
            "mot": (None if x.get("mot_pure") is None
                    else round(float(x["mot_pure"]), 4)),
            "p": round(float(p1[i]), 4), "q": round(float(q1[i]), 4),
        } for i, x in enumerate(sorted(lanes, key=lambda z: z["lane"]))]
    races[:] = [r for r in races if not (r["jcd"] == jcd and r["rno"] == rno)]
    races.append(rec)
    races.sort(key=lambda r: (r.get("close") or "", r["jcd"]))

    # 古い日の内訳は落とす（履歴が膨らむ）
    keep = sorted({d["date"] for d in days})[-KEEP_DETAIL_DAYS:]
    for d in days:
        if d["date"] not in keep:
            for r in d.get("races") or []:
                r.pop("lanes", None)

    h["days"] = sorted(days, key=lambda d: d["date"])
    h["updated"] = datetime.now(OF.JST).isoformat(timespec="seconds")
    _save(SITE, h)


def site_run(date):
    """この回が動いたことを history.json に残す（心拍）。

    ★対象レースが無い回は何も書かずに戻っていたので、
      「動いていない」のか「動いたが対象が無かった」のか区別できなかった。
      daily.py の誤報の原因。
    """
    h = _load(SITE, {}) or {}
    days = h.get("days") or []
    day = next((d for d in days if d["date"] == date), None)
    if day is None:
        day = {"date": date, "picks": [], "skipped": {}}
        days.append(day)
    day["runs"] = day.get("runs", 0) + 1
    day["last_run"] = datetime.now(OF.JST).strftime("%H:%M")
    h["days"] = sorted(days, key=lambda d: d["date"])
    h["updated"] = datetime.now(OF.JST).isoformat(timespec="seconds")
    _save(SITE, h)


def racecard(date, jcd, rno):
    """出走表。1レース1回だけ取り、cache に残す。

    ★info.kyotei.fun は GitHub Actions から時々まったく届かない（実測。
      同じコードで通る回と ConnectTimeout で全滅する回がある）。
      締切4〜30分前という短い窓でそれに当たると、そのレースは落とすしかない。
      prefetch.py で朝のうちに全レースぶん取って cache に入れておけば、
      本番の窓では取りに行かなくて済む。

      出走表の数値（勝率・モーター2連率など）は日中変わらないので、
      朝の値をそのまま使ってよい。展示タイムだけは朝には無いが、
      それは直前情報から補う（main を参照）。
    """
    path = f"{CACHE_DIR}/rc_{date}_{jcd:02d}_{rno}.json"
    c = _load(path)
    if c and len(c) == 6:
        return c
    rc = RC.fetch_racecard(date, jcd, rno)
    if rc and len(rc) == 6:
        _save(path, rc)
    return rc


def build_lanes(rc, page, jcd, rno, motor):
    """1レース6艇ぶんの特徴量入力を作る。

    出走表の数値(CARD)は info.kyotei.fun から   ← 学習データ raw/ と同じ取得元
    今節成績(SETSU)と登録番号は uchisankaku から ← 学習データ tokuten/ と同じ取得元
    この分担を崩すと、学習と本番で特徴量の中身が変わる(v23 の不具合)。
    """
    tkr = None
    for r in page["races"]:
        if r["rno"] == rno:
            tkr = r
            break
    if tkr is None or len(rc) != 6:
        return None
    tk = {x["lane"]: x for x in tkr["lanes"]}
    out = []
    for e in sorted(rc, key=lambda z: z["lane"]):
        x = tk.get(e["lane"], {})
        out.append({
            # --- 出走表 (info.kyotei.fun) ---
            "lane": e["lane"], "cls_val": e.get("cls_val"), "age": e.get("age"),
            "weight": e.get("weight"), "f_count": e.get("f_count"),
            "avg_st": e.get("avg_st"), "n_win": e.get("n_win"),
            "n_2ren": e.get("n_2ren"), "l_win": e.get("l_win"),
            "l_2ren": e.get("l_2ren"), "m_2ren": e.get("m_2ren"),
            "b_2ren": e.get("b_2ren"),
            "tenji": e.get("tenji") if e.get("tenji") else None,
            # --- 今節成績 (uchisankaku) ---
            "tok": x.get("tokuten"), "srank": x.get("rank"),
            "genten": x.get("genten"), "nruns": x.get("n_runs"),
            "st_setsu": x.get("st_setsu"), "c_win": x.get("c_win"),
            "c_ren3": x.get("c_ren3"), "c_st": x.get("c_st"),
            "toban": x.get("toban"), "name": x.get("name") or e.get("name"),
            # --- Kファイル (motor.py) ---
            "mot_pure": motor.get(str(x.get("toban"))),
        })
    if len(out) != 6:
        return None
    meta = {"jcd": jcd, "rno": rno,
            "day_no": page.get("day_no"), "n_days": page.get("n_days"),
            "is_final": 1 if any(w in (tkr.get("name") or "")
                                 for w in ("準優", "優勝", "選抜")) else 0}
    return out, meta


# ---------------------------------------------------------------- 通知
def notify(topic, jcd, rno, net, buy, cp, q, wave, wind):
    if not topic:
        print("    (ntfy トピック未設定なので通知しません)")
        return False
    import requests
    lines = [f"{F.COMBOS[i]}  {1.0/q[i]*0.748:.0f}倍相当  p/q {cp[i]/q[i]:.2f}"
             for i in buy]
    body = ("\n".join(lines) +
            f"\n{len(buy)}点 × {BET_YEN}円 = {len(buy)*BET_YEN:,}円"
            f"\n波{wave:.0f}cm 風{wind:.0f}m"
            "\n実測 回収率96%(確定オッズでの検証値。実運用は下がります)")
    payload = {"topic": topic,
               "title": f"勝負 {VENUE.get(jcd, jcd)} {rno}R  ネット{net}締切",
               "message": body, "priority": 4, "tags": ["fire"]}
    try:
        r = requests.post("https://ntfy.sh", json=payload, timeout=15)
        if r.status_code >= 300:
            print(f"    ntfy応答 {r.status_code}: {r.text[:120]}")
        return r.status_code < 300
    except Exception as e:
        print(f"    ntfy失敗 {type(e).__name__}")
        return False


# ---------------------------------------------------------------- 本体
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYYMMDD。省略すると今日")
    ap.add_argument("--dry", action="store_true", help="通知せず結果だけ出す")
    ap.add_argument("--win", default=None,
                    help="動作確認用。締切まで何分〜何分を対象にするか 例 4,600")
    ap.add_argument("--budget", type=int, default=200,
                    help="この秒数を過ぎたら新しいレースに着手しない")
    args = ap.parse_args()
    t0 = time.time()
    win_lo, win_hi = WIN_LO, WIN_HI
    if args.win:
        win_lo, win_hi = (int(x) for x in args.win.split(","))
        print(f"★動作確認モード 締切{win_lo}〜{win_hi}分前を対象にします")

    now = datetime.now(OF.JST)
    date = args.date or now.strftime("%Y%m%d")
    topic = os.environ.get("NTFY_TOPIC", "")
    prune(date)
    model = load_model()
    motor = load_motor()

    st_path = f"{STATE_DIR}/notified_{date}.json"
    # --dry では通知済みを見ない(同じ日に何度でも同じ結果が出せるように)
    done = set() if args.dry else set(_load(st_path, []) or [])

    if not args.dry:
        site_run(date)          # ここまで来たら「動いた」と記録する

    # 1. 淡水は最初から見ない
    targets = [j for j in VENUE if j not in SR.TANSUI]
    print(f"対象の場 {len(targets)}場 (淡水{len(SR.TANSUI)}場は除外)")

    # 2. 締切まで WIN_LO〜WIN_HI 分のレースを拾う
    sched = close_times(date, targets, deadline=t0 + args.budget * 0.6)
    todo = []
    for jcd, times in sched.items():
        for rno, hhmm in enumerate(times, start=1):
            net = OF.net_close(hhmm)
            left = OF.mins_left(net, now)
            key = f"{jcd}-{rno}"
            if left is None or not (win_lo <= left <= win_hi) or key in done:
                continue
            todo.append((jcd, rno, net, left))
    todo.sort(key=lambda z: z[3])
    print(f"締切{win_lo}〜{win_hi}分前のレース {len(todo)}件"
          + (f"  (通知済み {len(done)}件)" if done else ""))
    if not todo:
        return

    bought = 0
    skips = {}          # 見送りの内訳（サイトに出す）

    def skip(reason):
        skips[reason] = skips.get(reason, 0) + 1

    for k, (jcd, rno, net, left) in enumerate(todo):
        # ★持ち時間を超えたら打ち切る。GitHub Actions のジョブ上限に当たると
        #   通知済みの記録も残らないまま丸ごと捨てられる（実測で経験）。
        if time.time() - t0 > args.budget:
            print(f"  持ち時間{args.budget}秒を超えたので"
                  f"残り{len(todo)-k}件は次の回へ")
            break
        left = OF.mins_left(net, datetime.now(OF.JST))   # 時計を取り直す
        if left is None or left < win_lo:
            print(f"  {VENUE.get(jcd, jcd)} {rno}R 締切に間に合わないので見送り")
            continue
        tag = f"{VENUE.get(jcd, jcd)} {rno}R (あと{left}分)"
        # 3. 直前情報 → 波・風で足切り
        info = BI.fetch(date, jcd, rno)
        wave, wind = BI.wave_wind(info)
        if not SR.race_ok(jcd, wave, wind):
            print(f"  {tag} 見送り  波{wave} 風{wind}")
            skip("波・風" if wave is not None else "データ欠")
            if not args.dry:
                site_race(date, VENUE.get(jcd, str(jcd)), jcd, rno, net,
                          "波・風" if wave is not None else "気象が取れない",
                          wave, wind)
            continue
        pg = card(date, jcd)
        if not pg:
            print(f"  {tag} 今節成績が取れません")
            skip("データ欠")
            if not args.dry:
                site_race(date, VENUE.get(jcd, str(jcd)), jcd, rno, net, "今節成績が取れません", wave, wind)
            continue
        rc = racecard(date, jcd, rno)
        if not rc:
            print(f"  {tag} 出走表が取れません")
            skip("データ欠")
            if not args.dry:
                site_race(date, VENUE.get(jcd, str(jcd)), jcd, rno, net, "出走表が取れません", wave, wind)
            continue
        got = build_lanes(rc, pg, jcd, rno, motor)
        if not got:
            print(f"  {tag} 出走表の形が違います")
            skip("データ欠")
            if not args.dry:
                site_race(date, VENUE.get(jcd, str(jcd)), jcd, rno, net, "出走表の形が違います", wave, wind)
            continue
        lanes, meta = got
        # 展示タイムは出走表側を優先し、無ければ直前情報で補う
        for x in lanes:
            if not x.get("tenji"):
                x["tenji"] = (info.get("tenji") or {}).get(x["lane"])
        if sum(1 for x in lanes if x.get("tenji")) < 6:
            print(f"  {tag} 展示タイムがまだ出ていません")
            skip("データ欠")
            if not args.dry:
                site_race(date, VENUE.get(jcd, str(jcd)), jcd, rno, net, "展示タイムがまだ出ていません", wave, wind)
            continue
        # ★「純度が3艇未満なら見送り」を外した（2026-09-04、メモ §23）。
        #   このガードは select_rule.py に無い。つまり95.3%のバックテストは
        #   節初日のレースも買っていた。本番だけが違う母集団を買っていた。
        #   捨てていたレースを測ると 回収率95.7% / 実測/市場 1.290 で遜色なし。
        #   買い目の12%を理由なく捨てていたことになる。
        #   壊れ検知は load_motor（空・3日以上古い）と motor.yml（500人未満で失敗）
        #   の二段で足りている。個別レースのガードは節初日を弾いていただけ。
        nmot = sum(1 for x in lanes if x.get("mot_pure") is not None)
        # 4. オッズ
        if time.time() - t0 > args.budget + 60:
            print(f"  {tag} 持ち時間を大きく超えたので中止")
            break
        odds = OF.fetch_odds(date, jcd, rno)
        q, q1 = F.market_probs(odds) if odds else (None, None)
        if q is None:
            print(f"  {tag} オッズが取れません")
            skip("データ欠")
            if not args.dry:
                site_race(date, VENUE.get(jcd, str(jcd)), jcd, rno, net, "オッズが取れません",
                          wave, wind, nmot=nmot)
            continue
        X = F.build_race(lanes, meta, q1)
        raw = np.asarray(model.predict(X), dtype=float)
        p1 = raw / raw.sum()
        cp = F.trifecta(p1, q)
        buy = SR.pick(q, cp)
        if not buy:
            print(f"  {tag} 買い目なし  波{wave:.0f}cm 風{wind:.0f}m")
            skip("帯の外／p/q不足")
            if not args.dry:
                site_race(date, VENUE.get(jcd, str(jcd)), jcd, rno, net, "買い目なし",
                          wave, wind, lanes, p1, q1, nmot=nmot)
            continue
        print(f"  {tag} ★{len(buy)}点  波{wave:.0f}cm 風{wind:.0f}m  "
              + " ".join(f"{F.COMBOS[i]}(p/q {cp[i]/q[i]:.2f})" for i in buy))
        if args.dry:
            continue
        if notify(topic, jcd, rno, net, buy, cp, q, wave, wind):
            done.add(f"{jcd}-{rno}")
            site_log(date, VENUE.get(jcd, str(jcd)), jcd, rno, net,
                     buy, cp, q, odds, wave, wind, None,
                     lanes=lanes, p1=p1, q1=q1, nmot=nmot)
            site_race(date, VENUE.get(jcd, str(jcd)), jcd, rno, net, "買い",
                      wave, wind, lanes, p1, q1, npt=len(buy), nmot=nmot)
            _save(st_path, sorted(done))   # ★1件ごとに残す。まとめて最後に
            bought += 1                    #   書くと、途中で落ちた回のぶんが
                                           #   記録されず二重通知になる
    if not args.dry and skips:
        site_log(date, None, None, None, None, None, None, None, None,
                 None, None, skips)
    print(f"通知 {bought}件")


if __name__ == "__main__":
    main()
