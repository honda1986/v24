#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""browser.py -- 専用プロファイルの Chrome を開く

加入者番号・暗証番号はどこにも保存しない。
login モードで手で入れてもらい、その Chrome プロファイルを使い回す。
セッションが切れたら login をやり直す。

profile_dir は .gitignore に入れてある。絶対に共有しないこと。
"""
import contextlib
import os


class BrowserUnavailable(Exception):
    pass


@contextlib.contextmanager
def open_context(cfg):
    """(context, page) を渡す。終わったら必ず閉じる"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise BrowserUnavailable(
            "playwright が入っていません。\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        )

    user_data_dir = cfg.path("profile_dir")
    os.makedirs(user_data_dir, exist_ok=True)
    kwargs = {
        "user_data_dir": user_data_dir,
        "headless": bool(cfg.headless),    # 既定は False。画面が見えるほうが事故に気づける
        "viewport": {"width": 1280, "height": 900},
    }
    if cfg.use_installed_chrome:
        kwargs["channel"] = "chrome"

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(**kwargs)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            yield context, page
        finally:
            with contextlib.suppress(Exception):
                context.close()
