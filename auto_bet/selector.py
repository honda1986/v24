#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selector.py -- 「いま買うべき組」を選ぶ。ネットも画面も触らない純関数

★通知された組を、そのまま買う。
  buys[].odds は通知した時点のオッズで、投票する頃には動いている。
  だからといって、いまのオッズで p/q を計算し直して条件を見直してはいけない。
  v24 は通知した時点の判断で買う前提で検証されている。投票時に再判定すると
  検証していない別のルールになり、成績が何を意味するのか分からなくなる。
"""
from dataclasses import dataclass

from bet_store import make_key
from jst import minutes_to_close

KIND_OBI = "帯"
KIND_ANA = "穴"

# 場コード → 場名。history.json には place が入っているが、欠けたときの控え
PLACES = {
    1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖",
    7: "蒲郡", 8: "常滑", 9: "津", 10: "三国", 11: "びわこ", 12: "住之江",
    13: "尼崎", 14: "鳴門", 15: "丸亀", 16: "児島", 17: "宮島", 18: "徳山",
    19: "下関", 20: "若松", 21: "芦屋", 22: "福岡", 23: "唐津", 24: "大村",
}


@dataclass(frozen=True)
class Bet:
    date: str
    jcd: int
    place: str
    rno: int
    kind: str
    close: str
    combo: str
    yen: int
    points: int          # そのレースの点数（1レース何点の中の1点か）
    minutes: float       # 選んだ時点で締切まで何分あったか
    key: str

    @property
    def label(self):
        return f"{self.place}{self.rno}R"


@dataclass
class Result:
    bets: list
    warnings: list       # 人に見せる警告（点数が想定外、上限に達した、など）


def _combos(race):
    """buys から組だけ取り出す。重複と空は落とす"""
    out = []
    for b in race.get("buys") or []:
        if not isinstance(b, dict):
            continue
        c = b.get("combo")
        if isinstance(c, str) and c.strip() and c.strip() not in out:
            out.append(c.strip())
    return out


def select(day, done_keys, spent_yen, cfg, at):
    """今この瞬間に投票すべき組を、締切が近い順に返す

    day        : history.json の今日ぶんの要素（無ければ None）
    done_keys  : bet_done.json にすでにあるキーの集合
    spent_yen  : 今日すでに使った額
    at         : いまの JST 時刻
    """
    warnings = []
    if not isinstance(day, dict):
        return Result([], warnings)          # 今日の日付が days に無い日も落ちない

    date = day.get("date")
    if not isinstance(date, str) or not date:
        return Result([], warnings)

    sources = []
    if cfg.buy_obi:
        sources.append((KIND_OBI, day.get("picks") or []))
    if cfg.buy_ana:
        sources.append((KIND_ANA, day.get("ana") or []))   # ana が無い日もある

    cands = []
    seen = set()
    for kind, races in sources:
        if not isinstance(races, list):
            continue
        for race in races:
            if not isinstance(race, dict):
                continue
            jcd, rno = race.get("jcd"), race.get("rno")
            close = race.get("close")
            if not isinstance(jcd, int) or not isinstance(rno, int):
                continue
            place = race.get("place") or PLACES.get(jcd) or f"場{jcd}"

            minutes = minutes_to_close(date, close, at)
            if minutes is None:
                warnings.append(f"{place}{rno}R {kind}: close が読めない（{close!r}）。見送り")
                continue
            # 締切まで N 分未満は投票しない（押している途中で締め切られるのを防ぐ）
            # 締切まで M 分を超えていても投票しない（オッズがまだ動く）
            # 大きく負（もう過ぎた）も、ここで黙って落ちる
            if not (cfg.close_min_minutes <= minutes <= cfg.close_max_minutes):
                continue

            combos = _combos(race)
            if not combos:
                continue
            # 1レースの点数が想定を超えたら、そのレースごと見送って警告
            # （実測の上限は 帯2点 / 穴側3点。4点以上が来たら異常）
            if cfg.max_points_per_race is not None and len(combos) > cfg.max_points_per_race:
                warnings.append(
                    f"★{place}{rno}R {kind}: {len(combos)}点は想定外"
                    f"（上限 {cfg.max_points_per_race}点）。レースごと見送り"
                )
                continue

            for combo in combos:
                key = make_key(date, jcd, rno, combo, kind)
                if key in done_keys or key in seen:   # すでに投票済み／同じ組が二度出た
                    continue
                seen.add(key)
                cands.append(Bet(
                    date=date, jcd=jcd, place=place, rno=rno, kind=kind,
                    close=close, combo=combo, yen=cfg.bet_yen,
                    points=len(combos), minutes=round(minutes, 1), key=key,
                ))

    # 締切が近いものから。同じ締切なら場・R の順
    cands.sort(key=lambda b: (b.minutes, b.jcd, b.rno, b.kind, b.combo))

    if cfg.max_yen_per_day is None:
        return Result(cands, warnings)

    # 1日の上限。使用額は bet_done.json の当日分から数えている
    left = cfg.max_yen_per_day - spent_yen
    bets = []
    for b in cands:
        if left < b.yen:
            warnings.append(
                f"1日の上限 {cfg.max_yen_per_day}円 に達したので、"
                f"残り{len(cands) - len(bets)}点は見送り（使用済み {spent_yen}円）"
            )
            break
        bets.append(b)
        left -= b.yen
    return Result(bets, warnings)
