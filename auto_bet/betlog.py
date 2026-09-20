#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""betlog.py -- 1行1イベントで追記するログ

  時刻 / モード / 場・R / 種別 / 組 / 点数 / 金額 / 結果
"""
import os
import sys

from jst import now

SEP = "\t"


class Log:
    def __init__(self, path, mode, echo=True):
        self.path = path
        self.mode = mode
        self.echo = echo

    def _write(self, cols):
        line = SEP.join(str(c) for c in cols)
        if self.echo:
            print(line, flush=True)
        try:
            d = os.path.dirname(os.path.abspath(self.path))
            if d:
                os.makedirs(d, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            print(f"（ログを書けません: {e}）", file=sys.stderr, flush=True)

    def bet(self, b, result, note=""):
        self._write([
            now().strftime("%Y-%m-%d %H:%M:%S"), self.mode, b.label, b.kind,
            b.combo, f"{b.points}点", f"{b.yen}円", result,
            f"締切{b.close}(あと{b.minutes:.0f}分) {note}".strip(),
        ])

    def event(self, result, note=""):
        self._write([
            now().strftime("%Y-%m-%d %H:%M:%S"), self.mode, "-", "-", "-", "-", "-",
            result, note,
        ])
