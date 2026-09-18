#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bet_store.py -- 投票済みの記録（bet_done.json）

二重投票を防ぐための、いちばん大事なファイル。

- キーは 日付-場コード-R-組-種別（例 20260918-24-9-2-1-4-帯）
- 同じレースが picks と ana の両方に出ることはある。帯と穴側は別勘定なので、
  レース単位で重複排除しない。キーに種別が入っているのはそのため
- 投票が成功したら、その場で即書く（まとめて最後に書かない）
- 書き込みは一時ファイル → os.replace で原子的に
- 起動時に必ず読む。壊れていたら空で続行せず、止まる
"""
import json
import os
import tempfile

from jst import now

VERSION = 1


class BetDoneCorrupt(Exception):
    """bet_done.json が読めない。空で続行してはいけない"""


def make_key(date, jcd, rno, combo, kind):
    return f"{date}-{jcd}-{rno}-{combo}-{kind}"


class BetStore:
    def __init__(self, path):
        self.path = path
        self.bets = self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            raise BetDoneCorrupt(f"{self.path} を読めません: {e}")
        if not isinstance(data, dict) or not isinstance(data.get("bets"), dict):
            raise BetDoneCorrupt(f"{self.path} の形が違います（bets が辞書ではない）")
        for key, rec in data["bets"].items():
            if not isinstance(rec, dict) or "yen" not in rec or "date" not in rec:
                raise BetDoneCorrupt(f"{self.path} の {key} が壊れています")
        return data["bets"]

    def has(self, key):
        return key in self.bets

    def keys(self):
        return set(self.bets)

    def spent_on(self, date):
        """その日に使った額（円）"""
        return sum(
            int(r.get("yen") or 0) for r in self.bets.values() if r.get("date") == date
        )

    def record(self, bet, mode, note=""):
        """1件ぶん記録して、その場で書き切る"""
        if bet.key in self.bets:
            raise RuntimeError(f"二重投票を検知しました: {bet.key}")
        self.bets[bet.key] = {
            "date": bet.date,
            "jcd": bet.jcd,
            "place": bet.place,
            "rno": bet.rno,
            "kind": bet.kind,
            "combo": bet.combo,
            "yen": bet.yen,
            "close": bet.close,
            "mode": mode,
            "at": now().strftime("%Y-%m-%d %H:%M:%S"),
            "note": note,
        }
        self._save()

    def _save(self):
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".bet_done-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": VERSION, "bets": self.bets}, f,
                          ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
