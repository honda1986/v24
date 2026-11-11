#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rawsrc.py -- v22 の raw / tokuten を読む。空や欠けの日は v24 が公式から作ったもの（raw24/ tokuten24/）で代える

★v22 の raw は 2026-10-20 から毎日0レース（info.kyotei.fun に GitHub から届かない）、
  tokuten も 10/19 で止まった。ほかにもぽつぽつ空の日がある（2025-02-25 など）。
  collect_raw.py が公式（出走表・確定3連単オッズ・Kファイル）から同じ形で作るので、
  bt.py / train.py / settle.py はここを通して読む（band_howto.md §31）。
  ★raw24 の出走表は公式の値。体重・F数・当地勝率・当地2連率の4つは info.kyotei.fun と
    定義が違う（§30。入れ替えても帯の買い目は89%同じ）。
"""
import glob
import gzip
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RAW24 = os.path.join(HERE, "raw24")
TOK24 = os.path.join(HERE, "tokuten24")


def _load(path):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def raw_days(raw_dir, raw24=RAW24):
    """日付（YYYYMMDD 文字列）の一覧。v22 と raw24 の和"""
    return sorted({os.path.basename(p)[:8] for d in (raw_dir, raw24) if d
                   for p in glob.glob(f"{d}/*.json.gz")})


def load_raw(raw_dir, date, raw24=RAW24):
    """その日の raw。v22 にレースがあればそれ、無ければ raw24。どちらも無ければ races 空"""
    rd = _load(f"{raw_dir}/{date}.json.gz") if raw_dir else None
    if rd and rd.get("races"):
        return rd
    r24 = _load(f"{raw24}/{date}.json.gz") if raw24 else None
    if r24 and r24.get("races"):
        return r24
    return rd or {"date": date, "races": []}


def tokuten_files(tok_dir, tok24=TOK24):
    """{日付: パス}。v22 にあればそれ、無い日は tokuten24"""
    out = {os.path.basename(x)[:8]: x for x in glob.glob(f"{tok24}/*.json.gz")} if tok24 else {}
    if tok_dir:
        out.update({os.path.basename(x)[:8]: x for x in glob.glob(f"{tok_dir}/*.json.gz")})
    return out
