#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""history_source.py -- v24 が push した history.json を読むだけ

★書き込まないこと。予想側（GitHub Actions）の push と衝突して記録が壊れる。

raw.githubusercontent.com は最大5分ほどキャッシュされる。
Cache-Control ヘッダだけでは CDN に効かないので、
URL の末尾に毎回変わるクエリ（?t=<epoch>）を必ず付ける。
それでも数分遅れることはあり、締切ぎりぎりのレースは取り逃す。
これは仕組み上の限界で、実害は「たまに買えない」だけ。買いすぎる方には転ばない。
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

TIMEOUT = 20


def is_url(src):
    """http:// などで始まっていれば URL。それ以外はファイルの場所とみなす

    Windows の "C:\\boat\\v24\\history.json" は URL ではない（"://" が無い）。
    """
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*://", str(src)))


def read_file(path):
    """同じ PC の history.json を直接読む（v24 も PC で動かしている場合）

    ★yosou が書いている最中に読むと、途中までの JSON を読むことがある。
      そのときは取れなかったことにして、次の周に回す。
    """
    if str(path).lower().startswith("file://"):
        path = str(path)[7:].lstrip("/") if os.name == "nt" else str(path)[7:]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None, f"ファイルがありません: {path}"
    except (OSError, UnicodeDecodeError) as e:
        return None, f"読めず: {e}"
    except json.JSONDecodeError as e:
        return None, f"書き込み中かもしれません（{e}）"
    if not isinstance(data, dict) or not isinstance(data.get("days"), list):
        return None, "形が違う（days が無い）"
    return data, ""


def bust(url, t=None):
    """キャッシュ避けのクエリを足す"""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}t={int(t if t is not None else time.time())}"


def fetch(url, timeout=TIMEOUT, opener=urllib.request.urlopen):
    """取れたら dict、取れなければ (None, 理由)

    ネットが切れていても落ちないこと。その周は何もせず次へ。
    URL でなければ、同じ PC のファイルとして読む（キャッシュの遅れが無くなる）。
    """
    if not is_url(url):
        return read_file(url)
    req = urllib.request.Request(
        bust(url),
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "v24-auto-bet/1.0",
        },
    )
    try:
        with opener(req, timeout=timeout) as res:
            raw = res.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
        return None, f"取得できず: {e}"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, f"中身が読めず: {e}"
    if not isinstance(data, dict) or not isinstance(data.get("days"), list):
        return None, "形が違う（days が無い）"
    return data, ""


def pick_day(history, date):
    """今日の date に一致する要素だけ取り出す。無ければ None

    days は古い日も消えないので、日が経つほど膨らむ。今日のぶん以外は捨てる。
    """
    if not isinstance(history, dict):
        return None
    for day in history.get("days") or []:
        if isinstance(day, dict) and day.get("date") == date:
            return day
    return None
