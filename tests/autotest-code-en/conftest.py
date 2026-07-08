# -*- coding: utf-8 -*-
"""pytest 配置：将 scripts/ 加入 sys.path，使测试可导入 lang 包。"""
import os
import sys

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
VARIANT = os.path.basename(TEST_DIR)  # "auto-test-zh" or "auto-test-en"
SCRIPTS_DIR = os.path.normpath(os.path.join(TEST_DIR, "..", "..", "skills", VARIANT, "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
