#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pc_selftest.py -- PC 移行ぶんの確かめ（runner と watchdog）

  python pc_selftest.py

GitHub にも競艇サイトにも触らない。git だけ使う。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(os.path.join(HERE, "tests"),
                                                top_level_dir=HERE)
    ok = unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()
    sys.exit(0 if ok else 1)
