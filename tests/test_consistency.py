# -*- coding: utf-8 -*-
"""zh/en 一致性测试 — 验证 scripts 目录内容完全一致。"""
import filecmp
import os
from pathlib import Path

import pytest

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(TEST_DIR, ".."))
ZH_SCRIPTS_DIR = os.path.join(REPO_ROOT, "skills", "autotest-code-zh", "scripts")
EN_SCRIPTS_DIR = os.path.join(REPO_ROOT, "skills", "autotest-code-en", "scripts")


def _collect_py_files(directory: str) -> list[str]:
    """递归收集目录下所有 .py 文件，返回相对路径列表。"""
    result = []
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(".py"):
                rel = os.path.relpath(
                    os.path.join(root, f), directory
                )
                result.append(rel)
    return sorted(result)


class TestScriptsConsistency:
    """验证 zh/en scripts 目录内容完全一致。"""

    def test_zh_scripts_dir_exists(self):
        """zh scripts 目录存在。"""
        assert os.path.isdir(ZH_SCRIPTS_DIR), f"zh scripts dir not found: {ZH_SCRIPTS_DIR}"

    def test_en_scripts_dir_exists(self):
        """en scripts 目录存在。"""
        assert os.path.isdir(EN_SCRIPTS_DIR), f"en scripts dir not found: {EN_SCRIPTS_DIR}"

    def test_py_file_lists_match(self):
        """zh/en scripts 下的 .py 文件列表一致。"""
        if not os.path.isdir(EN_SCRIPTS_DIR):
            pytest.skip("en scripts dir not found")
        zh_files = _collect_py_files(ZH_SCRIPTS_DIR)
        en_files = _collect_py_files(EN_SCRIPTS_DIR)
        assert zh_files == en_files, (
            f"File lists differ:\n"
            f"only in zh: {set(zh_files) - set(en_files)}\n"
            f"only in en: {set(en_files) - set(zh_files)}"
        )

    def test_py_file_contents_match(self):
        """zh/en scripts 下每个 .py 文件内容一致。"""
        if not os.path.isdir(EN_SCRIPTS_DIR):
            pytest.skip("en scripts dir not found")
        zh_files = _collect_py_files(ZH_SCRIPTS_DIR)
        en_files = _collect_py_files(EN_SCRIPTS_DIR)
        if zh_files != en_files:
            pytest.skip("file lists differ, skip content comparison")
        mismatches = []
        for rel in zh_files:
            zh_path = os.path.join(ZH_SCRIPTS_DIR, rel)
            en_path = os.path.join(EN_SCRIPTS_DIR, rel)
            if not filecmp.cmp(zh_path, en_path, shallow=False):
                mismatches.append(rel)
        assert not mismatches, f"Content mismatch in: {mismatches}"
