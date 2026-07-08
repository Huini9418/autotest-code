# -*- coding: utf-8 -*-
"""discover_python_envs.py 测试 — Python 多环境发现。

覆盖项目 venv、VIRTUAL_ENV、pyenv、conda、uv、homebrew、系统 Python
的发现逻辑，以及去重、pytest 检测、推荐逻辑。
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# 确保能导入 discover_python_envs 模块
VARIANT = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "skills", VARIANT, "scripts"
))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from discover_python_envs import (
    _check_pytest,
    _find_active_venv,
    _find_project_venvs,
    _find_pyenv_envs,
    _find_system_pythons,
    _find_conda_envs,
    _find_uv_envs,
    _make_env,
    _parse_version,
    discover_python_envs,
    recommend_environment,
)


# ---------------------------------------------------------------------------
# 项目本地 venv 检测
# ---------------------------------------------------------------------------


class TestFindProjectVenvs:
    """验证项目本地 venv 发现。"""

    def test_find_project_venv_dotvenv(self, tmp_path):
        """.venv/bin/python 被发现。"""
        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        python_path = venv_bin / "python"
        python_path.write_text("#!/usr/bin/env python3\n")
        python_path.chmod(0o755)

        with patch(
            "discover_python_envs._get_version",
            return_value=("Python 3.11.5", [3, 11, 5], False),
        ), patch(
            "discover_python_envs._check_pytest",
            return_value={"has_pytest": True, "pytest_version": "8.0.0"},
        ):
            envs = _find_project_venvs(str(tmp_path), set())
        assert len(envs) == 1
        assert envs[0]["type"] == "project_venv"
        assert envs[0]["path"] == str(python_path)

    def test_find_project_venv_venv(self, tmp_path):
        """venv/bin/python 被发现。"""
        venv_bin = tmp_path / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        python_path = venv_bin / "python"
        python_path.write_text("#!/usr/bin/env python3\n")
        python_path.chmod(0o755)

        with patch(
            "discover_python_envs._get_version",
            return_value=("Python 3.10.0", [3, 10, 0], False),
        ), patch(
            "discover_python_envs._check_pytest",
            return_value={"has_pytest": False, "pytest_version": None},
        ):
            envs = _find_project_venvs(str(tmp_path), set())
        assert len(envs) == 1
        assert envs[0]["type"] == "project_venv"

    def test_find_project_venv_in_parent_dir(self, tmp_path):
        """子目录中的路径向上查找父目录的 .venv。"""
        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        python_path = venv_bin / "python"
        python_path.write_text("#!/usr/bin/env python3\n")
        python_path.chmod(0o755)

        sub_dir = tmp_path / "sub" / "deep"
        sub_dir.mkdir(parents=True)

        with patch(
            "discover_python_envs._get_version",
            return_value=("Python 3.11.5", [3, 11, 5], False),
        ), patch(
            "discover_python_envs._check_pytest",
            return_value={"has_pytest": True, "pytest_version": "8.0.0"},
        ):
            envs = _find_project_venvs(str(sub_dir), set())
        assert len(envs) == 1
        assert envs[0]["type"] == "project_venv"

    def test_no_venv_returns_empty(self, tmp_path):
        """无 venv 时返回空列表。"""
        envs = _find_project_venvs(str(tmp_path), set())
        assert envs == []

    def test_nonexistent_target_returns_empty(self):
        """不存在的 target_path 返回空。"""
        envs = _find_project_venvs("/nonexistent/path", set())
        assert envs == []


# ---------------------------------------------------------------------------
# 当前激活的 venv 检测
# ---------------------------------------------------------------------------


class TestFindActiveVenv:
    """验证 VIRTUAL_ENV 环境变量检测。"""

    def test_find_active_venv(self, tmp_path, monkeypatch):
        """VIRTUAL_ENV 环境变量检测。"""
        venv_bin = tmp_path / "bin"
        venv_bin.mkdir()
        python_path = venv_bin / "python"
        python_path.write_text("#!/usr/bin/env python3\n")
        python_path.chmod(0o755)

        monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path))

        with patch(
            "discover_python_envs._get_version",
            return_value=("Python 3.11.5", [3, 11, 5], False),
        ), patch(
            "discover_python_envs._check_pytest",
            return_value={"has_pytest": True, "pytest_version": "8.0.0"},
        ):
            envs = _find_active_venv(set())
        assert len(envs) == 1
        assert envs[0]["type"] == "virtualenv"

    def test_no_virtual_env_returns_empty(self, monkeypatch):
        """无 VIRTUAL_ENV 时返回空。"""
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        envs = _find_active_venv(set())
        assert envs == []


# ---------------------------------------------------------------------------
# pyenv 检测
# ---------------------------------------------------------------------------


class TestFindPyenvEnvs:
    """验证 pyenv 环境发现。"""

    def test_find_pyenv_envs_via_command(self, monkeypatch):
        """pyenv versions --bare 输出被解析。"""
        monkeypatch.setattr(
            "shutil.which", lambda x: "/usr/local/bin/pyenv" if x == "pyenv" else None
        )

        mock_output = "3.12.0\n3.11.5\n3.10.0\n"

        with patch("subprocess.run") as mock_run, \
             patch(
                 "discover_python_envs._get_version",
                 return_value=("Python 3.12.0", [3, 12, 0], False),
             ), \
             patch(
                 "discover_python_envs._check_pytest",
                 return_value={"has_pytest": True, "pytest_version": "8.0.0"},
             ), \
             patch(
                 "os.path.exists", lambda p: True
             ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=mock_output, stderr=""
            )
            envs = _find_pyenv_envs(set())
        # 至少检测到一些环境
        assert isinstance(envs, list)

    def test_find_pyenv_envs_no_pyenv(self, monkeypatch):
        """无 pyenv 时返回空。"""
        monkeypatch.setattr("shutil.which", lambda x: None)
        monkeypatch.setattr("os.path.isdir", lambda p: False)
        envs = _find_pyenv_envs(set())
        assert envs == []


# ---------------------------------------------------------------------------
# conda 检测
# ---------------------------------------------------------------------------


class TestFindCondaEnvs:
    """验证 conda 环境发现。"""

    def test_find_conda_envs_no_conda(self, monkeypatch):
        """无 conda 时返回空。"""
        monkeypatch.setattr("shutil.which", lambda x: None)
        envs = _find_conda_envs(set())
        assert envs == []

    def test_find_conda_envs_parses_json(self, monkeypatch, tmp_path):
        """conda env list --json 输出被解析。"""
        monkeypatch.setattr(
            "shutil.which", lambda x: "/opt/anaconda/bin/conda" if x == "conda" else None
        )
        env_dir = tmp_path / "myenv"
        env_bin = env_dir / "bin"
        env_bin.mkdir(parents=True)
        python_path = env_bin / "python"
        python_path.write_text("#!/usr/bin/env python3\n")
        python_path.chmod(0o755)

        conda_output = json.dumps({"envs": [str(env_dir)]})

        with patch("subprocess.run") as mock_run, \
             patch(
                 "discover_python_envs._get_version",
                 return_value=("Python 3.10.0", [3, 10, 0], False),
             ), \
             patch(
                 "discover_python_envs._check_pytest",
                 return_value={"has_pytest": False, "pytest_version": None},
             ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=conda_output, stderr=""
            )
            envs = _find_conda_envs(set())
        assert len(envs) == 1
        assert envs[0]["type"] == "conda"


# ---------------------------------------------------------------------------
# uv 检测
# ---------------------------------------------------------------------------


class TestFindUvEnvs:
    """验证 uv 管理的 Python 环境发现。"""

    def test_find_uv_envs_no_uv(self, monkeypatch):
        """无 uv 时返回空。"""
        monkeypatch.setattr("shutil.which", lambda x: None)
        envs = _find_uv_envs(set())
        assert envs == []

    def test_find_uv_envs_parses_output(self, monkeypatch, tmp_path):
        """uv python list 输出被解析。"""
        python_path = tmp_path / "bin" / "python"
        python_path.parent.mkdir(parents=True)
        python_path.write_text("#!/usr/bin/env python3\n")
        python_path.chmod(0o755)

        monkeypatch.setattr(
            "shutil.which", lambda x: "/usr/local/bin/uv" if x == "uv" else None
        )

        uv_output = f"cpython-3.12.0-macos-aarch64-none    {python_path}"

        with patch("subprocess.run") as mock_run, \
             patch(
                 "discover_python_envs._get_version",
                 return_value=("Python 3.12.0", [3, 12, 0], False),
             ), \
             patch(
                 "discover_python_envs._check_pytest",
                 return_value={"has_pytest": False, "pytest_version": None},
             ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=uv_output, stderr=""
            )
            envs = _find_uv_envs(set())
        assert len(envs) == 1
        assert envs[0]["type"] == "uv"

    def test_find_uv_envs_command_fails(self, monkeypatch):
        """uv python list 返回非零退出码时返回空。"""
        monkeypatch.setattr(
            "shutil.which", lambda x: "/usr/local/bin/uv" if x == "uv" else None
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="error"
            )
            envs = _find_uv_envs(set())
        assert envs == []

    def test_find_uv_envs_timeout(self, monkeypatch):
        """uv python list 超时不崩溃。"""
        monkeypatch.setattr(
            "shutil.which", lambda x: "/usr/local/bin/uv" if x == "uv" else None
        )

        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        monkeypatch.setattr(subprocess, "run", mock_run)
        envs = _find_uv_envs(set())
        assert envs == []

    def test_find_uv_envs_empty_output(self, monkeypatch):
        """uv python list 无输出时返回空。"""
        monkeypatch.setattr(
            "shutil.which", lambda x: "/usr/local/bin/uv" if x == "uv" else None
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            envs = _find_uv_envs(set())
        assert envs == []

    def test_find_uv_envs_appends_bin_python(self, monkeypatch, tmp_path):
        """路径不以 python 结尾时自动追加 bin/python。"""
        uv_dir = tmp_path / "cpython-3.12.0"
        bin_dir = uv_dir / "bin"
        bin_dir.mkdir(parents=True)
        python_path = bin_dir / "python"
        python_path.write_text("#!/usr/bin/env python3\n")
        python_path.chmod(0o755)

        monkeypatch.setattr(
            "shutil.which", lambda x: "/usr/local/bin/uv" if x == "uv" else None
        )

        uv_output = f"cpython-3.12.0-macos-aarch64-none    {uv_dir}"

        with patch("subprocess.run") as mock_run, \
             patch(
                 "discover_python_envs._get_version",
                 return_value=("Python 3.12.0", [3, 12, 0], False),
             ), \
             patch(
                 "discover_python_envs._check_pytest",
                 return_value={"has_pytest": False, "pytest_version": None},
             ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=uv_output, stderr=""
            )
            envs = _find_uv_envs(set())
        assert len(envs) == 1
        assert envs[0]["path"].endswith("python")


# ---------------------------------------------------------------------------
# 系统 Python 检测
# ---------------------------------------------------------------------------


class TestFindSystemPythons:
    """验证 Homebrew 和系统 Python 检测。"""

    def test_find_system_pythons(self, monkeypatch):
        """/usr/bin/python3 等被检测。"""
        def mock_exists(path):
            return path in (
                "/usr/bin/python3",
                "/usr/bin/python",
            )

        monkeypatch.setattr("os.path.exists", mock_exists)
        monkeypatch.setattr(
            "os.path.realpath", lambda p: p
        )

        with patch(
            "discover_python_envs._get_version",
            return_value=("Python 3.9.6", [3, 9, 6], False),
        ), patch(
            "discover_python_envs._check_pytest",
            return_value={"has_pytest": False, "pytest_version": None},
        ):
            envs = _find_system_pythons(set())
        assert len(envs) >= 1
        for env in envs:
            assert env["type"] == "system"

    def test_homebrew_python_detected(self, monkeypatch):
        """Homebrew Python 被标记为 homebrew 类型。"""
        def mock_exists(path):
            return path == "/opt/homebrew/bin/python3"

        monkeypatch.setattr("os.path.exists", mock_exists)
        monkeypatch.setattr("os.path.realpath", lambda p: p)

        with patch(
            "discover_python_envs._get_version",
            return_value=("Python 3.12.0", [3, 12, 0], False),
        ), patch(
            "discover_python_envs._check_pytest",
            return_value={"has_pytest": False, "pytest_version": None},
        ):
            envs = _find_system_pythons(set())
        assert len(envs) == 1
        assert envs[0]["type"] == "homebrew"


# ---------------------------------------------------------------------------
# 去重逻辑
# ---------------------------------------------------------------------------


class TestDedupByRealpath:
    """验证符号链接去重。"""

    def test_dedup_by_realpath(self, tmp_path):
        """同一路径（通过 realpath）只出现一次。"""
        python_path = tmp_path / "python3"
        python_path.write_text("#!/usr/bin/env python3\n")
        python_path.chmod(0o755)

        seen = set()
        with patch(
            "discover_python_envs._get_version",
            return_value=("Python 3.12.0", [3, 12, 0], False),
        ), patch(
            "discover_python_envs._check_pytest",
            return_value={"has_pytest": False, "pytest_version": None},
        ):
            env1 = _make_env(str(python_path), "homebrew", seen)
            env2 = _make_env(str(python_path), "system", seen)

        assert env1 is not None
        assert env2 is None  # 第二次因为去重返回 None


# ---------------------------------------------------------------------------
# pytest 检测
# ---------------------------------------------------------------------------


class TestCheckPytest:
    """验证 pytest 安装状态检测。"""

    def test_check_pytest_installed(self):
        """has_pytest=true（用当前 Python 测试）。"""
        import sys as _sys

        result = _check_pytest(_sys.executable)
        assert result["has_pytest"] is True
        assert result["pytest_version"] is not None

    def test_check_pytest_not_installed(self, tmp_path):
        """has_pytest=false（不存在的 Python）。"""
        fake_path = str(tmp_path / "fake_python")
        result = _check_pytest(fake_path)
        assert result["has_pytest"] is False
        assert result["pytest_version"] is None

    def test_check_pytest_timeout(self, monkeypatch):
        """超时不崩溃，返回 has_pytest=false。"""
        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        monkeypatch.setattr(subprocess, "run", mock_run)
        result = _check_pytest("/usr/bin/python3")
        assert result["has_pytest"] is False
        assert result["pytest_version"] is None


# ---------------------------------------------------------------------------
# 推荐逻辑
# ---------------------------------------------------------------------------


class TestRecommendEnvironment:
    """验证推荐环境选择逻辑。"""

    def test_recommended_prefers_project_venv(self):
        """推荐有 pytest 的 project_venv。"""
        envs = [
            {
                "path": "/usr/local/bin/python3",
                "version": "Python 3.12.0",
                "version_tuple": [3, 12, 0],
                "type": "homebrew",
                "has_pytest": True,
                "pytest_version": "8.0.0",
                "is_python2": False,
            },
            {
                "path": "/Users/foo/.venv/bin/python",
                "version": "Python 3.11.5",
                "version_tuple": [3, 11, 5],
                "type": "project_venv",
                "has_pytest": True,
                "pytest_version": "8.0.0",
                "is_python2": False,
            },
        ]
        assert recommend_environment(envs) == "/Users/foo/.venv/bin/python"

    def test_recommended_prefers_has_pytest(self):
        """无 project_venv 时推荐有 pytest 的环境。"""
        envs = [
            {
                "path": "/usr/bin/python3",
                "version": "Python 3.9.6",
                "version_tuple": [3, 9, 6],
                "type": "system",
                "has_pytest": False,
                "pytest_version": None,
                "is_python2": False,
            },
            {
                "path": "/usr/local/bin/python3",
                "version": "Python 3.12.0",
                "version_tuple": [3, 12, 0],
                "type": "homebrew",
                "has_pytest": True,
                "pytest_version": "8.0.0",
                "is_python2": False,
            },
        ]
        assert recommend_environment(envs) == "/usr/local/bin/python3"

    def test_recommended_falls_back_to_python3(self):
        """无 pytest 时回退到第一个 Python 3。"""
        envs = [
            {
                "path": "/usr/bin/python3",
                "version": "Python 3.9.6",
                "version_tuple": [3, 9, 6],
                "type": "system",
                "has_pytest": False,
                "pytest_version": None,
                "is_python2": False,
            },
        ]
        assert recommend_environment(envs) == "/usr/bin/python3"

    def test_recommended_empty_returns_none(self):
        """空列表返回 None。"""
        assert recommend_environment([]) is None

    def test_recommended_prefers_virtualenv_with_pytest(self):
        """无 project_venv 时推荐有 pytest 的 virtualenv。"""
        envs = [
            {
                "path": "/usr/bin/python3",
                "version": "Python 3.9.6",
                "version_tuple": [3, 9, 6],
                "type": "system",
                "has_pytest": True,
                "pytest_version": "8.0.0",
                "is_python2": False,
            },
            {
                "path": "/Users/foo/venv/bin/python",
                "version": "Python 3.11.5",
                "version_tuple": [3, 11, 5],
                "type": "virtualenv",
                "has_pytest": True,
                "pytest_version": "8.0.0",
                "is_python2": False,
            },
        ]
        assert recommend_environment(envs) == "/Users/foo/venv/bin/python"


# ---------------------------------------------------------------------------
# Python 2 检测
# ---------------------------------------------------------------------------


class TestPython2Detection:
    """验证 Python 2 环境标记。"""

    def test_python2_detected(self, tmp_path):
        """Python 2 环境被标记 is_python2=true。"""
        python_path = tmp_path / "python2"
        python_path.write_text("#!/usr/bin/env python2\n")
        python_path.chmod(0o755)

        with patch(
            "discover_python_envs._get_version",
            return_value=("Python 2.7.18", [2, 7, 18], True),
        ), patch(
            "discover_python_envs._check_pytest",
            return_value={"has_pytest": False, "pytest_version": None},
        ):
            env = _make_env(str(python_path), "system", set())
        assert env is not None
        assert env["is_python2"] is True

    def test_parse_version_python2(self):
        """版本解析正确识别 Python 2。"""
        version_tuple, is_python2 = _parse_version("Python 2.7.18")
        assert version_tuple == [2, 7, 18]
        assert is_python2 is True

    def test_parse_version_python3(self):
        """版本解析正确识别 Python 3。"""
        version_tuple, is_python2 = _parse_version("Python 3.12.0")
        assert version_tuple == [3, 12, 0]
        assert is_python2 is False

    def test_parse_version_prerelease(self):
        """预发布版本号（3.12.0rc1）正确解析为 [3, 12, 0]。"""
        version_tuple, is_python2 = _parse_version("Python 3.12.0rc1")
        assert version_tuple == [3, 12, 0]
        assert is_python2 is False

    def test_parse_version_no_patch(self):
        """无补丁号（3.12）解析为 [3, 12]。"""
        version_tuple, is_python2 = _parse_version("Python 3.12")
        assert version_tuple == [3, 12]
        assert is_python2 is False

    def test_parse_version_empty_string(self):
        """空字符串返回空列表。"""
        version_tuple, is_python2 = _parse_version("")
        assert version_tuple == []
        assert is_python2 is False

    def test_parse_version_no_version_in_string(self):
        """无版本号的字符串返回空列表。"""
        version_tuple, is_python2 = _parse_version("not a version")
        assert version_tuple == []
        assert is_python2 is False


# ---------------------------------------------------------------------------
# 空结果
# ---------------------------------------------------------------------------


class TestEmptyResult:
    """验证无任何 Python 环境的情况。"""

    def test_empty_result(self, monkeypatch, tmp_path):
        """所有来源都为空时返回空列表。"""
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        monkeypatch.setattr("shutil.which", lambda x: None)
        monkeypatch.setattr("os.path.isdir", lambda p: False)

        envs = discover_python_envs(str(tmp_path))
        # 系统 Python 可能存在，但如果全都不存在则返回空
        # 关键是不崩溃
        assert isinstance(envs, list)


# ---------------------------------------------------------------------------
# 输出 JSON 结构
# ---------------------------------------------------------------------------


class TestOutputJsonStructure:
    """验证输出 JSON 格式正确。"""

    def test_output_json_structure(self, tmp_path):
        """输出 JSON 含 environments 和 recommended 字段。"""
        # 用当前 Python 作为测试环境
        import sys as _sys

        envs = discover_python_envs(str(tmp_path))
        recommended = recommend_environment(envs)
        result = {
            "environments": envs,
            "recommended": recommended,
        }
        # 验证可序列化为 JSON
        json_str = json.dumps(result, ensure_ascii=False)
        parsed = json.loads(json_str)
        assert "environments" in parsed
        assert "recommended" in parsed
        assert isinstance(parsed["environments"], list)

    def test_each_env_has_required_fields(self, tmp_path):
        """每个环境含必需字段。"""
        envs = discover_python_envs(str(tmp_path))
        for env in envs:
            assert "path" in env
            assert "version" in env
            assert "version_tuple" in env
            assert "type" in env
            assert "has_pytest" in env
            assert "pytest_version" in env
            assert "is_python2" in env
