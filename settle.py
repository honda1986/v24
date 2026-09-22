#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""settle.py -- 買った記録に結果と「オッズの目減り」を入れる（予想サイト用）

history.json の picks は、通知した時点では結果が空。翌日 Kファイルが出たら
的中したか・払戻がいくらかを入れる。motor.yml が毎朝 v22 の kfile を
持ってくるので、そのついでに走らせる。

  python settle.py --kfile /tmp/v22/kfile

★紙で回している間の唯一の答え合わせなので、ここが狂うと何も分からなくなる。
  だから「Kファイルにそのレースが無い」場合は空のままにして、
  勝手に不的中扱いにはしない。

★もうひとつの仕事：オッズの目減りを測る（2026-09-03 追加）
  バックテストの95.3%は「確定オッズ」で測った値。実際は締切前のオッズを見て
  買うので、そこから動く。どれだけ目減りするかは今まで誰も測っていなかった。
  v22 の raw に確定オッズ120通りが翌朝そろうので、通知時に記録したオッズと
  突き合わせる。
  ・raw のオッズが確定値であることは実測で確認済み（4,558レース、98.0%が
    Kファイルの払戻と完全一致）
  ・買った組が「確定オッズでも p/q>1.05 を満たしたか」も併せて数える。
    満たさなくなっていたら、それは選別そのものが幻だったということ
"""
import argparse
import datetime
import glob
import gzip
import io
import json
import os
import urllib.error
import urllib.request

SITE = "history.json"
BET_YEN = 100
PQ_MIN = 1.05          # select_rule と同じ。補正なしで買ったときの基準
# ★帯は補正の組み合わせでしきい値が変わる（select_rule と同じ値を置く）。
#   ここを PQ_MIN(1.05) のままにすると、1.15 で買った組を 1.05 で判定して
#   しまい、「確定オッズでも基準を満たしたまま」がほぼ素通りの数字になる。
#   ★2026-09-20 より前に買った記録は 1.097/1.078 で選ばれているので、
#     新しい基準で見ると厳しめに出る（見落としではなく安全側のずれ）。
# ★帯のしきい値は途中で変えている。買った当時の基準で見ないと、
#   「確定オッズでも基準を満たしたまま」の数字が二重にずれる。
#   新しい世代を前に足すこと（date >= start の最初のものを使う）。
#   ★20260921 は切り替え日なので 1.15 で買ったぶんが少し混じりうる。
#     1.14 との差は小さいので、世代はこの粒度で足りる。
BAND_ERAS = [
    ("20260921", {"g+h": 1.14, "g": 1.11, "base": PQ_MIN}),   # 窓を4〜15分に
    ("00000000", {"g+h": 1.097, "g": 1.078, "base": PQ_MIN}),
]
# ★穴側の記録を数え始める日。これ以前は別ルール（1.097・通知して買った）や、
#   別の窓（4〜30分）で拾ったぶんなので混ぜない（ana_howto.md §8 の事前登録）。
SWITCH = "20260921"


def band_th(date, pick):
    """その買い目が実際に選ばれたときのしきい値"""
    for start, tbl in BAND_ERAS:
        if (date or "") >= start:
            return tbl.get(pick.get("rule"), PQ_MIN)
    return PQ_MIN
PQ_ANA = 1.15          # 穴側(試験)のしきい値。select_rule.ANA_PQ_MIN と同じ
                       # ★2026-09-20 に 1.097 から変更。それ以前の記録を
                       #   混ぜて数えると基準が揃わないので注意
RAW_URL = "https://raw.githubusercontent.com/honda1986/v22/main/raw/{}.json.gz"
K_URL = "https://raw.githubusercontent.com/honda1986/v22/main/kfile/{}.json.gz"

COMBOS = [f"{a}-{b}-{c}" for a in range(1, 7) for b in range(1, 7) if b != a
          for c in range(1, 7) if c not in (a, b)]
CIX = {c: i for i, c in enumerate(COMBOS)}


def fetch_gz(path, url):
    """手元のファイル、無ければ URL から1日ぶんだけ取る。取れなければ None。

    ★2026-09-22: kfile はここを見ていなかった（raw だけ URL に落ちていた）。
      PC 側の v22 の git pull が失敗すると kfile が古いまま止まり、
      settle が「Kファイルがまだありません」と言い続けて結果が入らなくなる。
      実際に 09/20・09/21 の結果が2日ぶん入らなかった。
      手元の clone に依存しないよう、kfile も URL へ落とせるようにする。
    """
    if os.path.exists(path):
        try:
            return open(path, "rb").read()
        except OSError:
            pass
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read()
    except (urllib.error.URLError, OSError, ValueError):
        return None


def kmap(kdir, date):
    """その日の着順と3連単の払戻。(jcd,rno) -> (組, 払戻)。取れなければ None。"""
    blob = fetch_gz(f"{kdir}/{date}.json.gz", K_URL.format(date))
    if blob is None:
        return None
    try:
        with gzip.open(io.BytesIO(blob), "rt", encoding="utf-8") as f:
            rd = json.load(f)
    except (OSError, ValueError):
        return None
    out = {}
    for r in rd.get("races") or []:
        if r.get("hit"):
            out[(r["jcd"], r["rno"])] = (r["hit"], float(r.get("pay_3t") or 0))
    # ★空の辞書は「Kファイルはあるが中身が無い」＝まだ確定していない、と読む。
    #   None を返して次の周に持ち越す（空を返すと全部が「結果が取れない」になる）
    return out or None


def rawmap(rawdir, date):
    """その日の確定オッズ。(jcd,rno) -> 120個のリスト。取れなければ None。

    ★手元に無ければ v22 リポジトリから1日ぶん(70KB程度)だけ取る。
      raw を丸ごと checkout すると60MB超になるので、それは避ける。
    """
    blob = fetch_gz(f"{rawdir}/{date}.json.gz", RAW_URL.format(date))
    if blob is None:
        return None
    try:
        with gzip.open(io.BytesIO(blob), "rt", encoding="utf-8") as f:
            rd = json.load(f)
    except (OSError, ValueError):
        return None
    out = {}
    for r in rd.get("races") or []:
        od = r.get("odds")
        if od and len(od) == 120 and all(x and x > 0 for x in od):
            out[(r["jcd"], r["rno"])] = od
    return out or None


def shadow(pick, odds120, combo):
    """採用しなかったほうの作り方なら、どうだったか（メモ §34）。

    ★実際には買っていない。前向きの比較のためだけの記録。
      買った組と重なっていても構わない。別勘定で持つ。
    """
    bg = pick.get("buys_alt")
    if bg is None:
        bg = pick.get("buys_g")      # 旧い記録との互換
    if bg is None:
        return
    pick["cost_g"] = len(bg) * BET_YEN
    if combo in bg and combo in CIX:
        pick["hit_g"] = True
        pick["ret_g"] = float(odds120[CIX[combo]]) * BET_YEN
    else:
        pick["hit_g"] = False
        pick["ret_g"] = 0.0


def drift(pick, odds120, pq_min=PQ_MIN):
    """通知時オッズ → 確定オッズ を、買った組ごとに書き込む。

    確定オッズから市場確率 q を作り直し、p/q がまだ基準を超えているかも見る。
    """
    inv = [1.0 / o for o in odds120]
    tot = sum(inv)
    kept = 0
    for b in pick.get("buys") or []:
        i = CIX.get(b["combo"])
        if i is None:
            continue
        fo = float(odds120[i])
        fq = inv[i] / tot
        b["fodds"] = round(fo, 1)
        b["fq"] = round(fq, 5)
        b["fpq"] = round(float(b["p"]) / fq, 3) if fq > 0 else None
        b["move"] = round(fo / float(b["odds"]), 3) if b.get("odds") else None
        if b["fpq"] is not None and b["fpq"] > pq_min:
            kept += 1
    pick["kept"] = kept
    return kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kfile", default="../v22/kfile")
    ap.add_argument("--raw", default="../v22/raw")
    args = ap.parse_args()

    try:
        with open(SITE, encoding="utf-8") as f:
            h = json.load(f)
    except (OSError, ValueError):
        print(f"{SITE} がありません。まだ1件も通知が出ていません")
        return

    filled = waiting = afilled = 0
    stale = []          # 2日以上前なのに結果が入っていない日
    # ★Kファイルは翌朝に出る。前日ぶんが未確定なのは普通。
    #   2日以上前が残っていたら、取り込みのどこかが止まっている
    cutoff = (datetime.date.today() - datetime.timedelta(days=2)).strftime("%Y%m%d")
    for day in h.get("days") or []:
        pend = [p for p in day.get("picks") or [] if p.get("hit") is None]
        # 目減りだけまだ入っていないレースも拾う（結果が先に入った場合）
        rm = rawmap(args.raw, day["date"])
        nod = [p for p in day.get("picks") or []
               if any("fodds" not in b for b in (p.get("buys") or []))]
        if rm:
            for p in nod:
                od = rm.get((p["jcd"], p["rno"]))
                if od:
                    drift(p, od, band_th(day["date"], p))
        # ★穴側(試験)も同じ突き合わせをする。ただし別勘定（メモ §41）。
        apend = [p for p in day.get("ana") or [] if p.get("hit") is None]
        if rm:
            for p in day.get("ana") or []:
                if any("fodds" not in b for b in (p.get("buys") or [])):
                    od = rm.get((p["jcd"], p["rno"]))
                    if od:
                        drift(p, od, PQ_ANA)
        if not pend and not apend:
            continue
        km = kmap(args.kfile, day["date"])
        if km is None:
            waiting += len(pend) + len(apend)
            print(f"  {day['date']} Kファイルがまだありません"
                  f"（{len(pend)+len(apend)}件は結果待ち）")
            if day["date"] < cutoff:
                stale.append((day["date"], len(pend) + len(apend)))
            continue
        for p in pend:
            got = km.get((p["jcd"], p["rno"]))
            if not got:
                waiting += 1
                continue
            combo, pay = got
            won = [b for b in p["buys"] if b["combo"] == combo]
            p["combo"] = combo
            p["pay"] = pay
            p["hit"] = bool(won)
            # 1点100円なので、払戻は「オッズ×100」＝ pay をそのまま受け取る
            p["ret"] = pay if won else 0.0
            od = (rm or {}).get((p["jcd"], p["rno"]))
            if od is not None:
                shadow(p, od, combo)
            filled += 1
        for p in apend:
            got = km.get((p["jcd"], p["rno"]))
            if not got:
                waiting += 1
                continue
            combo, pay = got
            won = [b for b in p["buys"] if b["combo"] == combo]
            p["combo"] = combo
            p["pay"] = pay
            p["hit"] = bool(won)
            p["ret"] = pay if won else 0.0
            afilled += 1

    with open(SITE, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False)

    if stale:
        print()
        print("★★ 2日以上前なのに結果が入っていない日があります ★★")
        for dt, n in stale:
            print(f"    {dt}  {n}件")
        print("    v22 の kfile が取れていません。ふだんは手元の "
              "../v22/kfile を見て、無ければ GitHub から落とします。")
        print("    どちらも駄目ということは、ネットに出られていないか、"
              "v22 にその日の K ファイルがまだ入っていません。")

    # 通しの成績を出す
    dated = [(d["date"], p) for d in (h.get("days") or [])
             for p in (d.get("picks") or [])]
    picks = [p for _, p in dated]
    done = [p for p in picks if p.get("hit") is not None]
    cost = sum(p.get("cost") or 0 for p in done)
    ret = sum(p.get("ret") or 0 for p in done)
    print(f"\n結果を入れた {filled}件"
          + (f"（＋穴側 {afilled}件）" if afilled else "")
          + f" / 結果待ち {waiting}件")
    if done:
        print(f"確定 {len(done)}レース  的中 {sum(1 for p in done if p['hit'])}  "
              f"回収率 {ret/cost*100:.1f}%  収支 {ret-cost:+,.0f}円")
        print("★60レースを超えるまでは、ほぼ運の範囲。数字が動いても慌てないこと")
    else:
        print("まだ確定したレースがありません")

    # --- 穴側(試験)の成績。★帯とは混ぜない ---
    # ★2026-09-20 までの記録は p/q>1.097 の別ルールで、しかも通知して買った
    #   ぶん。いまのシャドー（1.15・記録のみ）と混ぜて回収率を出すと、
    #   ana_howto.md §8 の事前登録が意味をなさなくなる。日付で切る。
    ana = [p for d in (h.get("days") or []) if d["date"] > SWITCH
           for p in (d.get("ana") or [])]
    ana_old = sum(len(d.get("ana") or []) for d in (h.get("days") or [])
                  if d["date"] <= SWITCH)
    adone = [p for p in ana if p.get("hit") is not None]
    if ana or ana_old:
        acost = sum(p.get("cost") or 0 for p in adone)
        aret = sum(p.get("ret") or 0 for p in adone)
        print(f"\n穴側(試験・シャドー / p/q>1.15 / {SWITCH} より後) "
              f"{len(ana)}レース "
              f"{sum(len(p.get('buys') or []) for p in ana)}点 / 確定 {len(adone)}レース")
        if ana_old:
            print(f"  （{SWITCH} 以前の {ana_old}レースは p/q>1.097 の別ルール。"
                  "混ぜないので数えていません）")
        if acost:
            print(f"  的中 {sum(1 for p in adone if p['hit'])}  "
                  f"回収率 {aret/acost*100:.1f}%  収支 {aret-acost:+,.0f}円"
                  "  ★通知も投票もしていない記録だけの数字")
            print("  ★的中50本を超えるまでは判定しない（ana_howto.md §8 の事前登録）。"
                  "1.097 時代の 153.6% は別ルールの数字なので比べないこと")

    # --- オッズの目減り ---
    mv = [b["move"] for p in picks for b in (p.get("buys") or [])
          if b.get("move")]
    if mv:
        mv.sort()
        n = len(mv)
        avg = sum(mv) / n
        med = mv[n // 2]
        dn = sum(1 for x in mv if x < 1.0) / n * 100
        # ★p["kept"] は drift を回した時点のしきい値で数えた値がそのまま
        #   残っている（確定オッズが入った回しか drift は走らない）。
        #   古い基準の数を新しい見出しで出すと二重にずれるので、
        #   保存してある fpq から毎回数え直す。
        kept = tot = 0
        ths = set()
        for dt, p in dated:
            bs = [b for b in (p.get("buys") or []) if b.get("fpq") is not None]
            if not bs:
                continue
            th = band_th(dt, p)
            ths.add(th)
            tot += len(bs)
            kept += sum(1 for b in bs if b["fpq"] > th)
        print(f"\nオッズの目減り（買った {n}組）")
        print(f"  通知時 → 確定   平均 {avg:.3f}倍  中央 {med:.3f}倍  "
              f"下がった {dn:.0f}%")
        if tot:
            lab = "/".join(f"{t:g}" for t in sorted(ths))
            print(f"  確定オッズでも p/q>{lab} を満たしたまま  "
                  f"{kept}/{tot}（{kept/tot*100:.0f}%）")
        print(f"  ★素朴な見積りでは回収率 {(avg-1)*100:+.1f}pt。"
              "ただし当たりやすさとの相関を無視した値なので、")
        print("    確定した実測の回収率が出るまでは目安に留めること")
    else:
        print("\n（確定オッズがまだ引けていないので、目減りは測れていません）")

    # --- 2着の補正を使っていたら（影の記録）---
    gd = [p for p in picks if p.get("hit_g") is not None]
    if gd:
        c0 = sum(p.get("cost") or 0 for p in gd)
        r0 = sum(p.get("ret") or 0 for p in gd)
        c1 = sum(p.get("cost_g") or 0 for p in gd)
        r1 = sum(p.get("ret_g") or 0 for p in gd)
        # ★rule は「実際に買ったほうの作り方」。yosou.py は m3 があれば
        #   "g+h" を書く。ここを rule=="g" だけで判定していたため、
        #   本番の既定値 "g+h" ではラベルが左右逆に出ていた（2026-09-13 修正）。
        rule = (gd[-1].get("rule") or "base")
        NAME = {"g+h": "2着＋3着の補正あり", "g": "2着の補正あり", "base": "補正なし"}
        used = NAME.get(rule, rule)
        alt = "補正なし" if rule in ("g", "g+h") else "補正あり"
        print(f"\n作り方の比べ（{len(gd)}レース / 実際に買ったのは {rule}）")
        print(f"  実際に買った方（{used}）"
              f"  {c0/BET_YEN:.0f}点  回収率 {r0/c0*100 if c0 else 0:.1f}%")
        print(f"  買わなかった方（{alt}）"
              f"      {c1/BET_YEN:.0f}点  回収率 {r1/c1*100 if c1 else 0:.1f}%")
        print("  ★60レースを超えるまでは何も言えない。数字が動いても慌てないこと")


if __name__ == "__main__":
    main()
