# -*- coding: utf-8 -*-
"""zh/en 一致性测试 — 验证 scripts 目录内容完全一致。

Codex 审查 GAP 9 修复：自动断言 zh/en scripts 一致，不依赖手动 diff。
"""
import filecmp
import os
from pathlib import Path

import pytest

# 当前测试文件所在目录：tests/autotest-code-{zh|en}/
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
LANG_SUFFIX = os.path.basename(TEST_DIR)  # "autotest-code-zh" or "autotest-code-en"
REPO_ROOT = os.path.normpath(os.path.join(TEST_DIR, "..", ".."))
# scripts 目录：skills/autotest-code-{zh|en}/scripts/
SCRIPTS_DIR = os.path.join(REPO_ROOT, "skills", LANG_SUFFIX, "scripts")
OTHER_SUFFIX = "autotest-code-en" if LANG_SUFFIX.endswith("-zh") else "autotest-code-zh"
OTHER_SCRIPTS_DIR = os.path.join(REPO_ROOT, "skills", OTHER_SUFFIX, "scripts")


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

    def test_scripts_dir_exists(self):
        """scripts 目录存在。"""
        assert os.path.isdir(SCRIPTS_DIR), f"scripts dir not found: {SCRIPTS_DIR}"

    def test_other_scripts_dir_exists(self):
        """对端 scripts 目录存在。"""
        assert os.path.isdir(
            OTHER_SCRIPTS_DIR
        ), f"other scripts dir not found: {OTHER_SCRIPTS_DIR}"

    def test_py_file_lists_match(self):
        """zh/en scripts 下的 .py 文件列表一致。"""
        if not os.path.isdir(OTHER_SCRIPTS_DIR):
            pytest.skip("other scripts dir not found")
        zh_files = _collect_py_files(SCRIPTS_DIR)
        en_files = _collect_py_files(OTHER_SCRIPTS_DIR)
        assert zh_files == en_files, (
            f"File lists differ:\n"
            f"only in zh: {set(zh_files) - set(en_files)}\n"
            f"only in en: {set(en_files) - set(zh_files)}"
        )

    def test_py_file_contents_match(self):
        """zh/en scripts 下每个 .py 文件内容一致。"""
        if not os.path.isdir(OTHER_SCRIPTS_DIR):
            pytest.skip("other scripts dir not found")
        zh_files = _collect_py_files(SCRIPTS_DIR)
        en_files = _collect_py_files(OTHER_SCRIPTS_DIR)
        if zh_files != en_files:
            pytest.skip("file lists differ, skip content comparison")
        mismatches = []
        for rel in zh_files:
            zh_path = os.path.join(SCRIPTS_DIR, rel)
            en_path = os.path.join(OTHER_SCRIPTS_DIR, rel)
            if not filecmp.cmp(zh_path, en_path, shallow=False):
                mismatches.append(rel)
        assert not mismatches, f"Content mismatch in: {mismatches}"

    def test_test_files_match(self):
        """zh/en tests 目录下的测试文件列表一致。"""
        other_test_dir = os.path.normpath(os.path.join(TEST_DIR, "..", OTHER_SUFFIX))
        if not os.path.isdir(other_test_dir):
            pytest.skip("other tests dir not found")
        zh_tests = _collect_py_files(TEST_DIR)
        en_tests = _collect_py_files(other_test_dir)
        assert zh_tests == en_tests, (
            f"Test file lists differ:\n"
            f"only in {LANG_SUFFIX}: {set(zh_tests) - set(en_tests)}\n"
            f"only in {OTHER_SUFFIX}: {set(en_tests) - set(zh_tests)}"
        )

    def test_test_file_contents_match(self):
        """zh/en tests 目录下每个测试文件内容一致。"""
        other_test_dir = os.path.normpath(os.path.join(TEST_DIR, "..", OTHER_SUFFIX))
        if not os.path.isdir(other_test_dir):
            pytest.skip("other tests dir not found")
        zh_tests = _collect_py_files(TEST_DIR)
        en_tests = _collect_py_files(other_test_dir)
        if zh_tests != en_tests:
            pytest.skip("test file lists differ, skip content comparison")
        mismatches = []
        for rel in zh_tests:
            zh_path = os.path.join(TEST_DIR, rel)
            en_path = os.path.join(other_test_dir, rel)
            if not filecmp.cmp(zh_path, en_path, shallow=False):
                mismatches.append(rel)
        assert not mismatches, f"Content mismatch in: {mismatches}"
