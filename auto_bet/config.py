#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config.py -- config.json を読んで、値の形を確かめる

上限の項目（max_yen_per_day / max_points_per_race）は null で無制限。
"_" で始まるキーは人間向けの覚書なので読み飛ばす。
相対パスは config.json のあるフォルダからの相対として解く
（run.bat をどこから叩いても同じ場所を見るため）。
"""
import json
import os
import shutil
from dataclasses import dataclass, field

DEFAULTS = {
    "i_have_read_the_terms": False,
    "bet_yen": 100,
    "max_yen_per_day": 2000,
    "max_points_per_race": 4,
    "buy_obi": True,
    "buy_ana": False,
    "close_min_minutes": 0,
    "close_max_minutes": 25,
    "history_url": "https://raw.githubusercontent.com/honda1986/v24/main/history.json",
    "history_path": "../history.json",
    "poll_seconds": 120,
    "keepalive_minutes": 5,
    "telebote_url": "",
    "profile_dir": "chrome_profile",
    "use_installed_chrome": True,
    "headless": False,
    "bet_done_path": "bet_done.json",
    "log_path": "logs/auto_bet.log",
    "shot_dir": "shots",
    "stop_file": "STOP",
}


class ConfigError(Exception):
    pass


@dataclass
class Config:
    base_dir: str = "."
    i_have_read_the_terms: bool = False
    bet_yen: int = 100
    max_yen_per_day: "int | None" = 2000
    max_points_per_race: "int | None" = 4
    buy_obi: bool = True
    buy_ana: bool = False
    close_min_minutes: float = 0
    close_max_minutes: float = 25
    history_url: str = DEFAULTS["history_url"]
    history_path: str = DEFAULTS["history_path"]
    poll_seconds: int = 120
    keepalive_minutes: int = 5
    telebote_url: str = ""
    profile_dir: str = "chrome_profile"
    use_installed_chrome: bool = True
    headless: bool = False
    bet_done_path: str = "bet_done.json"
    log_path: str = "logs/auto_bet.log"
    shot_dir: str = "shots"
    stop_file: str = "STOP"
    unknown_keys: list = field(default_factory=list)

    def path(self, name):
        """設定に書かれたパスを絶対パスにする"""
        p = getattr(self, name)
        return p if os.path.isabs(p) else os.path.join(self.base_dir, p)


def _as_bool(d, key):
    v = d.get(key, DEFAULTS[key])
    if not isinstance(v, bool):
        raise ConfigError(f"{key} は true / false で書いてください（いまは {v!r}）")
    return v


def _as_int(d, key, lo=None, hi=None):
    v = d.get(key, DEFAULTS[key])
    if isinstance(v, bool) or not isinstance(v, int):
        raise ConfigError(f"{key} は整数で書いてください（いまは {v!r}）")
    if lo is not None and v < lo:
        raise ConfigError(f"{key} は {lo} 以上にしてください（いまは {v}）")
    if hi is not None and v > hi:
        raise ConfigError(f"{key} は {hi} 以下にしてください（いまは {v}）")
    return v


def _as_limit(d, key):
    """null なら無制限。数値なら 1 以上"""
    v = d.get(key, DEFAULTS[key])
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ConfigError(f"{key} は整数か null（無制限）で書いてください（いまは {v!r}）")
    if v < 1:
        raise ConfigError(f"{key} は 1 以上か null にしてください（いまは {v}）")
    return v


def _as_num(d, key, lo=None):
    v = d.get(key, DEFAULTS[key])
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ConfigError(f"{key} は数値で書いてください（いまは {v!r}）")
    if lo is not None and v < lo:
        raise ConfigError(f"{key} は {lo} 以上にしてください（いまは {v}）")
    return float(v)


def _as_str(d, key, required=False):
    v = d.get(key, DEFAULTS[key])
    if not isinstance(v, str):
        raise ConfigError(f"{key} は文字列で書いてください（いまは {v!r}）")
    v = v.strip()
    if required and not v:
        raise ConfigError(f"{key} が空です")
    return v


def from_dict(d, base_dir="."):
    if not isinstance(d, dict):
        raise ConfigError("config.json の中身が辞書ではありません")
    cfg = Config(
        base_dir=base_dir,
        i_have_read_the_terms=_as_bool(d, "i_have_read_the_terms"),
        bet_yen=_as_int(d, "bet_yen", lo=100),
        max_yen_per_day=_as_limit(d, "max_yen_per_day"),
        max_points_per_race=_as_limit(d, "max_points_per_race"),
        buy_obi=_as_bool(d, "buy_obi"),
        buy_ana=_as_bool(d, "buy_ana"),
        close_min_minutes=_as_num(d, "close_min_minutes", lo=0),
        close_max_minutes=_as_num(d, "close_max_minutes", lo=0),
        history_url=_as_str(d, "history_url", required=True),
        history_path=_as_str(d, "history_path"),
        poll_seconds=_as_int(d, "poll_seconds", lo=10),
        keepalive_minutes=_as_int(d, "keepalive_minutes", lo=0),
        telebote_url=_as_str(d, "telebote_url"),
        profile_dir=_as_str(d, "profile_dir", required=True),
        use_installed_chrome=_as_bool(d, "use_installed_chrome"),
        headless=_as_bool(d, "headless"),
        bet_done_path=_as_str(d, "bet_done_path", required=True),
        log_path=_as_str(d, "log_path", required=True),
        shot_dir=_as_str(d, "shot_dir", required=True),
        stop_file=_as_str(d, "stop_file", required=True),
    )
    if cfg.bet_yen % 100:
        raise ConfigError(f"bet_yen は100円単位にしてください（いまは {cfg.bet_yen}）")
    if cfg.close_min_minutes >= cfg.close_max_minutes:
        raise ConfigError(
            f"close_min_minutes ({cfg.close_min_minutes}) は "
            f"close_max_minutes ({cfg.close_max_minutes}) より小さくしてください"
        )
    if cfg.max_yen_per_day is not None and cfg.max_yen_per_day < cfg.bet_yen:
        raise ConfigError(
            f"max_yen_per_day ({cfg.max_yen_per_day}) が bet_yen ({cfg.bet_yen}) より "
            "小さいので、1点も買えません"
        )
    if not cfg.buy_obi and not cfg.buy_ana:
        raise ConfigError("buy_obi も buy_ana も false です。どちらも買いません")
    known = set(DEFAULTS)
    cfg.unknown_keys = sorted(k for k in d if not k.startswith("_") and k not in known)
    return cfg


EXAMPLE = "config.example.json"


def ensure(path):
    """config.json が無ければ、見本（config.example.json）から作る

    ★config.json は git で配らないこと。人それぞれの設定（金額・約定を読んだか）が
      入るので、追跡させると PC 側で困る:
        - runner.py の reset --hard で毎回もとに戻される、か
        - 「データ以外が変わっている」と見なされて、毎周の取り込みが止まる
      配らなければ、どちらも起きない。消えても次の起動でここが作り直す。

    返すのは (パス, 人に伝えること)。
    """
    path = os.path.abspath(path)
    if os.path.exists(path):
        return path, ""
    sample = os.path.join(os.path.dirname(path), EXAMPLE)
    if not os.path.exists(sample):
        return path, ""
    shutil.copyfile(sample, path)
    return path, (f"{EXAMPLE} から {os.path.basename(path)} を作りました。"
                  "金額などは run.bat の「設定」から直せます")


def load(path):
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise ConfigError(f"設定ファイルがありません: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"config.json を読めません（JSON が壊れています）: {e}")
    return from_dict(d, base_dir=os.path.dirname(path))
