# -*- coding: utf-8 -*-
"""_get_version 函数直接测试。

_get_version 通过 subprocess 调用 python --version，现有测试全部 mock 绕过，
这里直接测试真实子进程调用和输出解析路径。
"""
import subprocess
import sys

import pytest

from discover_python_envs import _get_version


class TestGetVersionReal:
    """使用真实解释器测试 _get_version（不 mock）。"""

    def test_current_python_returns_version(self):
        """用当前 Python 解释器路径调用，应返回有效版本。"""
        version_str, version_tuple, is_python2 = _get_version(sys.executable)
        assert version_str is not None
        assert "Python" in version_str or version_str[0].isdigit()
        assert len(version_tuple) >= 2
        assert version_tuple[0] == sys.version_info.major
        assert is_python2 is False

    def test_returns_version_tuple_list(self):
        """version_tuple 是整数列表。"""
        _, version_tuple, _ = _get_version(sys.executable)
        assert isinstance(version_tuple, list)
        for v in version_tuple:
            assert isinstance(v, int)

    def test_is_python2_false_for_python3(self):
        """Python 3 解释器 is_python2 应为 False。"""
        _, _, is_python2 = _get_version(sys.executable)
        assert is_python2 is False


class TestGetVersionEdgeCases:
    """测试 _get_version 的边界情况。"""

    def test_nonexistent_path_returns_none(self):
        """不存在的路径返回 (None, [], False)。"""
        version_str, version_tuple, is_python2 = _get_version("/nonexistent/python")
        assert version_str is None
        assert version_tuple == []
        assert is_python2 is False

    def test_timeout_returns_none(self, monkeypatch):
        """子进程超时返回 (None, [], False)。"""
        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        monkeypatch.setattr(subprocess, "run", mock_run)
        version_str, version_tuple, is_python2 = _get_version("/usr/bin/python3")
        assert version_str is None
        assert version_tuple == []
        assert is_python2 is False

    def test_oserror_returns_none(self, monkeypatch):
        """OSError（如权限不足）返回 (None, [], False)。"""
        def mock_run(*args, **kwargs):
            raise OSError("Permission denied")

        monkeypatch.setattr(subprocess, "run", mock_run)
        version_str, version_tuple, is_python2 = _get_version("/usr/bin/python3")
        assert version_str is None
        assert version_tuple == []
        assert is_python2 is False

    def test_empty_output_returns_none(self, monkeypatch):
        """stdout 和 stderr 都为空时返回 None。"""
        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        version_str, version_tuple, is_python2 = _get_version("/usr/bin/python3")
        assert version_str is None

    def test_version_from_stderr(self, monkeypatch):
        """有些 Python（如 Python 2）把版本打印到 stderr，应能解析。"""
        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="Python 3.9.6"
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        version_str, version_tuple, is_python2 = _get_version("/usr/bin/python3")
        assert version_str == "Python 3.9.6"
        assert version_tuple == [3, 9, 6]
        assert is_python2 is False

    def test_version_from_stdout_preferred(self, monkeypatch):
        """stdout 有内容时优先用 stdout。"""
        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Python 3.11.5", stderr="warning"
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        version_str, version_tuple, is_python2 = _get_version("/usr/bin/python3")
        assert version_str == "Python 3.11.5"
        assert version_tuple == [3, 11, 5]

    def test_multiline_output_uses_first_line(self, monkeypatch):
        """多行输出只取第一行。"""
        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout="Python 3.12.0\nsome warning\nanother line",
                stderr="",
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        version_str, version_tuple, is_python2 = _get_version("/usr/bin/python3")
        assert version_str == "Python 3.12.0"
        assert version_tuple == [3, 12, 0]
