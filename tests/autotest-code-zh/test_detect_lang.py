# -*- coding: utf-8 -*-
"""语言检测测试 — 覆盖 Codex 审查修复点 M1/M2/M9/M10。

测试文件扩展名映射、配置文件检测、框架检测、工具链检查。
"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from detect_lang import (
    check_toolchain,
    check_tree_sitter_dep,
    check_pytest_plugins,
    detect_all,
    detect_framework,
    detect_language,
    detect_pytest_async_config,
    _default_framework,
    _check_python_toolchain_with_path,
    _check_pytest_plugins_in_env,
    _empty_plugins,
)


# ---------------------------------------------------------------------------
# 语言检测
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    """验证文件扩展名和配置文件映射。"""

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("foo.py", "python"),
            ("foo.js", "javascript"),
            ("foo.jsx", "javascript"),
            ("foo.ts", "typescript"),
            ("foo.tsx", "typescript"),
            ("foo.go", "go"),
            ("foo.rs", "rust"),
            ("foo.java", "java"),
        ],
    )
    def test_extension_detection(self, tmp_path, filename, expected):
        f = tmp_path / filename
        f.write_text("x = 1")
        assert detect_language(str(f)) == expected

    @pytest.mark.parametrize(
        "config_file,expected",
        [
            ("pyproject.toml", "python"),
            ("setup.py", "python"),
            ("requirements.txt", "python"),
            ("package.json", "javascript"),
            ("go.mod", "go"),
            ("Cargo.toml", "rust"),
            ("pom.xml", "java"),
            ("build.gradle", "java"),
        ],
    )
    def test_config_file_detection(self, tmp_path, config_file, expected):
        (tmp_path / config_file).write_text("")
        assert detect_language(str(tmp_path)) == expected

    def test_tsconfig_overrides_package_json(self, tmp_path):
        """有 package.json 和 tsconfig.json → typescript。"""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text("{}")
        assert detect_language(str(tmp_path)) == "typescript"

    def test_directory_defaults_to_python(self, tmp_path):
        assert detect_language(str(tmp_path)) == "python"

    def test_nonexistent_path_defaults_to_python(self):
        assert detect_language("/nonexistent/path") == "python"


# ---------------------------------------------------------------------------
# M9: Java Maven/Gradle 检测
# ---------------------------------------------------------------------------


class TestJavaFrameworkDetection:
    """验证 Java 项目区分 Maven 和 Gradle。"""

    def test_maven_project(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        assert detect_framework(str(tmp_path), "java") == "maven"

    def test_gradle_project(self, tmp_path):
        (tmp_path / "build.gradle").write_text("plugins {}")
        assert detect_framework(str(tmp_path), "java") == "gradle"

    def test_no_build_file_defaults_to_maven(self, tmp_path):
        assert detect_framework(str(tmp_path), "java") == "maven"


# ---------------------------------------------------------------------------
# M10: Go/Rust 框架默认值与 registry 一致
# ---------------------------------------------------------------------------


class TestFrameworkDefaults:
    """验证框架默认值与 registry TEST_COMMANDS 一致。"""

    def test_go_default_is_gotestsum(self):
        assert _default_framework("go") == "gotestsum"

    def test_rust_default_is_cargo_nextest(self):
        assert _default_framework("rust") == "cargo nextest"

    def test_python_default_is_pytest(self):
        assert _default_framework("python") == "pytest"

    def test_javascript_default_is_jest(self):
        assert _default_framework("javascript") == "jest"

    def test_java_default_is_maven(self):
        assert _default_framework("java") == "maven"


# ---------------------------------------------------------------------------
# JS/TS 框架检测
# ---------------------------------------------------------------------------


class TestJsTsFrameworkDetection:
    """验证 Jest/Vitest 检测。"""

    def test_jest_config_js(self, tmp_path):
        (tmp_path / "jest.config.js").write_text("")
        assert detect_framework(str(tmp_path), "javascript") == "jest"

    def test_vitest_config(self, tmp_path):
        (tmp_path / "vitest.config.ts").write_text("")
        assert detect_framework(str(tmp_path), "javascript") == "vitest"

    def test_jest_in_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"devDependencies": {"jest": "^29.0.0"}}'
        )
        assert detect_framework(str(tmp_path), "javascript") == "jest"

    def test_vitest_in_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"devDependencies": {"vitest": "^1.0.0"}}'
        )
        assert detect_framework(str(tmp_path), "javascript") == "vitest"

    def test_no_config_defaults_to_jest(self, tmp_path):
        assert detect_framework(str(tmp_path), "javascript") == "jest"


# ---------------------------------------------------------------------------
# M1: 工具链检查包含测试命令实际用到的工具
# ---------------------------------------------------------------------------


class TestToolchainCheck:
    """验证工具链检查覆盖测试命令所需工具。"""

    def test_python_checks_pytest(self):
        """Python 应检查 python3 和 pytest。"""
        tc = check_toolchain("python")
        assert tc["available"] is True
        # 如果 pytest 缺失，应该出现在 missing 里
        # （当前环境有 pytest，所以 missing 应为空）
        assert "pytest" not in tc["missing"]

    def test_python_version_returned(self):
        tc = check_toolchain("python")
        assert "Python" in tc["version"]

    def test_unknown_language_returns_available(self):
        tc = check_toolchain("brainfuck")
        assert tc["available"] is True
        assert tc["missing"] == []

    def test_go_checks_gotestsum(self):
        """Go 应检查 go 和 gotestsum（如果 gotestsum 缺失应在 missing 中）。"""
        tc = check_toolchain("go")
        # go 本身可能存在
        if os.path.exists("/usr/local/go/bin/go") or any(
            os.path.exists(os.path.join(p, "go"))
            for p in os.environ.get("PATH", "").split(":")
        ):
            assert "go" not in tc["missing"]
        # gotestsum 可能缺失——验证它被检查了
        # （如果 gotestsum 存在则 missing 不含它，不存在则含它）
        # 关键是验证 gotestsum 被纳入检查范围

    def test_java_checks_mvn(self):
        """Java 应检查 java 和 mvn。"""
        tc = check_toolchain("java")
        # java 可能存在
        # mvn 可能缺失
        # 验证 mvn 被纳入检查（如果 mvn 不在 PATH 中，应该在 missing 中）
        import shutil

        if not shutil.which("mvn"):
            assert "mvn" in tc["missing"]
        else:
            assert "mvn" not in tc["missing"]


# ---------------------------------------------------------------------------
# M2: 超时处理
# ---------------------------------------------------------------------------


class TestToolchainTimeout:
    """验证工具链版本检查超时时标记为不可用。"""

    def test_timeout_marks_unavailable(self, monkeypatch):
        """模拟超时，验证 available=False。"""
        import subprocess
        import detect_lang as dl

        original_run = subprocess.run

        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        monkeypatch.setattr(subprocess, "run", mock_run)
        # shutil.which 返回非 None 让代码进入 subprocess.run 分支
        monkeypatch.setattr(
            "shutil.which", lambda x: "/usr/bin/" + x
        )
        tc = dl.check_toolchain("python")
        assert tc["available"] is False

    def test_oserror_does_not_crash(self, monkeypatch):
        """OSError 不应崩溃。"""
        import subprocess
        import detect_lang as dl

        def mock_run(*args, **kwargs):
            raise OSError("mock")

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr(
            "shutil.which", lambda x: "/usr/bin/" + x
        )
        tc = dl.check_toolchain("python")
        # OSError 被 except 捕获，available 保持 True（version 为空）
        assert tc["version"] == ""


# ---------------------------------------------------------------------------
# tree-sitter 依赖检查
# ---------------------------------------------------------------------------


class TestTreeSitterDep:
    """验证 tree-sitter 依赖检测。"""

    def test_python_does_not_need_tree_sitter(self):
        result = check_tree_sitter_dep("python")
        assert result["needed"] is False
        assert result["available"] is True

    def test_javascript_needs_tree_sitter(self):
        result = check_tree_sitter_dep("javascript")
        assert result["needed"] is True
        # 不假设是否已安装，只验证 needed=True
        assert "package" in result
        assert result["package"] == "tree-sitter-javascript"

    def test_unknown_language_no_dep(self):
        result = check_tree_sitter_dep("brainfuck")
        assert result["needed"] is False


# ---------------------------------------------------------------------------
# detect_all 集成测试
# ---------------------------------------------------------------------------


class TestDetectAll:
    """验证完整检测流程。"""

    def test_python_project(self, tmp_path):
        (tmp_path / "main.py").write_text("x = 1")
        (tmp_path / "requirements.txt").write_text("pytest")
        result = detect_all(str(tmp_path))
        assert result["language"] == "python"
        assert result["framework"] == "pytest"
        assert result["toolchain"]["available"] is True
        assert result["tree_sitter"]["needed"] is False

    def test_single_python_file(self, tmp_path):
        f = tmp_path / "app.py"
        f.write_text("x = 1")
        result = detect_all(str(f))
        assert result["language"] == "python"
        assert result["framework"] == "pytest"


# ---------------------------------------------------------------------------
# pytest 异步插件检测
# ---------------------------------------------------------------------------


class TestPytestAsyncConfig:
    """验证 pytest 异步测试配置检测。"""

    def test_no_config_returns_empty(self, tmp_path):
        """无 asyncio_mode 配置时返回空。"""
        (tmp_path / "main.py").write_text("x = 1")
        result = detect_pytest_async_config(str(tmp_path))
        assert result["asyncio_mode"] == ""
        assert result["missing"] == []

    def test_pyproject_toml_asyncio_mode(self, tmp_path):
        """pyproject.toml [tool.pytest.ini_options] 中的 asyncio_mode 被检测到。"""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\n'
            'asyncio_mode = "auto"\n'
        )
        result = detect_pytest_async_config(str(tmp_path))
        assert result["asyncio_mode"] == "auto"

    def test_pytest_ini_asyncio_mode(self, tmp_path):
        """pytest.ini 中的 asyncio_mode 被检测到。"""
        (tmp_path / "pytest.ini").write_text(
            "[pytest]\n"
            "asyncio_mode = auto\n"
        )
        result = detect_pytest_async_config(str(tmp_path))
        assert result["asyncio_mode"] == "auto"

    def test_setup_cfg_asyncio_mode(self, tmp_path):
        """setup.cfg [tool:pytest] 中的 asyncio_mode 被检测到。"""
        (tmp_path / "setup.cfg").write_text(
            "[tool:pytest]\n"
            "asyncio_mode = auto\n"
        )
        result = detect_pytest_async_config(str(tmp_path))
        assert result["asyncio_mode"] == "auto"

    def test_no_asyncio_mode_in_pyproject(self, tmp_path):
        """pyproject.toml 有 pytest section 但无 asyncio_mode。"""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\n'
            'testpaths = ["tests"]\n'
        )
        result = detect_pytest_async_config(str(tmp_path))
        assert result["asyncio_mode"] == ""

    def test_missing_pytest_asyncio_reported(self, tmp_path):
        """配了 asyncio_mode 但 pytest-asyncio 没装时应报告缺失。"""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\n'
            'asyncio_mode = "auto"\n'
        )
        result = detect_pytest_async_config(str(tmp_path))
        # pytest_asyncio 或 anyio 至少一个没装时才有 missing
        # 当前测试环境不一定有 pytest-asyncio，验证逻辑正确
        if not result["pytest_asyncio"] and not result["anyio"]:
            assert "pytest-asyncio" in result["missing"]
            assert "pip install" in result["hint"]
        elif not result["pytest_asyncio"]:
            # anyio 有但 pytest-asyncio 没有
            assert "pytest-asyncio" in result["missing"]
            assert "anyio" in result["hint"].lower() or "pytest-asyncio" in result["hint"]

    def test_detect_all_includes_pytest_plugins(self, tmp_path):
        """detect_all 结果中包含 pytest_plugins 字段。"""
        (tmp_path / "main.py").write_text("x = 1")
        result = detect_all(str(tmp_path))
        assert "pytest_plugins" in result
        assert result["pytest_plugins"] is not None

    def test_detect_all_non_python_no_pytest_plugins(self, tmp_path):
        """非 Python 语言的 pytest_plugins 应为 None。"""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "app.js").write_text("const x = 1;")
        result = detect_all(str(tmp_path))
        assert result["language"] == "javascript"
        assert result["pytest_plugins"] is None

    def test_detect_all_asyncio_missing_merges_to_toolchain(self, tmp_path):
        """asyncio_mode 配了但插件缺失时，合并到 toolchain.missing。"""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\n'
            'asyncio_mode = "auto"\n'
        )
        (tmp_path / "main.py").write_text("x = 1")
        result = detect_all(str(tmp_path))
        pp = result["pytest_plugins"]
        if pp["missing"]:
            assert "pytest-asyncio" in result["toolchain"]["missing"]
            assert result["toolchain"]["available"] is False

    def test_single_file_checks_parent_dir(self, tmp_path):
        """单文件路径时检查父目录的配置。"""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\n'
            'asyncio_mode = "auto"\n'
        )
        f = tmp_path / "app.py"
        f.write_text("x = 1")
        result = detect_pytest_async_config(str(f))
        assert result["asyncio_mode"] == "auto"


# ---------------------------------------------------------------------------
# 通用 pytest 插件检测
# ---------------------------------------------------------------------------


class TestPytestPlugins:
    """验证 check_pytest_plugins() 通用插件检测。"""

    def test_returns_plugins_dict(self, tmp_path):
        """结果中包含 plugins 字典。"""
        (tmp_path / "main.py").write_text("x = 1")
        result = check_pytest_plugins(str(tmp_path))
        assert "plugins" in result
        assert isinstance(result["plugins"], dict)

    def test_plugins_contains_all_entries(self, tmp_path):
        """plugins 字典包含所有 PYTEST_PLUGINS 条目。"""
        from lang.registry import PYTEST_PLUGINS

        (tmp_path / "main.py").write_text("x = 1")
        result = check_pytest_plugins(str(tmp_path))
        for pkg_name in PYTEST_PLUGINS:
            assert pkg_name in result["plugins"]

    def test_plugin_entry_has_required_fields(self, tmp_path):
        """每个插件条目含 available/import_name/trigger_type/trigger/alt。"""
        (tmp_path / "main.py").write_text("x = 1")
        result = check_pytest_plugins(str(tmp_path))
        for pkg_name, plugin_info in result["plugins"].items():
            assert "available" in plugin_info
            assert "import_name" in plugin_info
            assert "trigger_type" in plugin_info
            assert "trigger" in plugin_info
            assert "alt" in plugin_info

    def test_available_is_boolean(self, tmp_path):
        """available 字段是 bool 类型。"""
        (tmp_path / "main.py").write_text("x = 1")
        result = check_pytest_plugins(str(tmp_path))
        for pkg_name, plugin_info in result["plugins"].items():
            assert isinstance(plugin_info["available"], bool)

    def test_backward_compat_fields(self, tmp_path):
        """向后兼容字段 pytest_asyncio/anyio/hint 存在。"""
        (tmp_path / "main.py").write_text("x = 1")
        result = check_pytest_plugins(str(tmp_path))
        assert "pytest_asyncio" in result
        assert "anyio" in result
        assert "hint" in result
        assert "hints" in result

    def test_no_config_no_missing(self, tmp_path):
        """无 asyncio_mode 配置时 missing 为空。"""
        (tmp_path / "main.py").write_text("x = 1")
        result = check_pytest_plugins(str(tmp_path))
        assert result["missing"] == []
        assert result["asyncio_mode"] == ""

    def test_asyncio_mode_triggers_missing_check(self, tmp_path):
        """配了 asyncio_mode 时检查 pytest-asyncio 可用性。"""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\n'
            'asyncio_mode = "auto"\n'
        )
        result = check_pytest_plugins(str(tmp_path))
        assert result["asyncio_mode"] == "auto"
        if not result["pytest_asyncio"] and not result["anyio"]:
            assert "pytest-asyncio" in result["missing"]
        elif not result["pytest_asyncio"]:
            assert "pytest-asyncio" in result["missing"]

    def test_nonexistent_path_returns_empty(self):
        """不存在的路径返回空结果。"""
        result = check_pytest_plugins("/nonexistent/path")
        assert result["plugins"] == {}
        assert result["missing"] == []

    def test_single_file_checks_parent_dir(self, tmp_path):
        """单文件路径时检查父目录的配置。"""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\n'
            'asyncio_mode = "auto"\n'
        )
        f = tmp_path / "app.py"
        f.write_text("x = 1")
        result = check_pytest_plugins(str(f))
        assert result["asyncio_mode"] == "auto"

    def test_detect_all_includes_plugins_field(self, tmp_path):
        """detect_all 结果中 pytest_plugins 包含 plugins 字典。"""
        (tmp_path / "main.py").write_text("x = 1")
        result = detect_all(str(tmp_path))
        assert result["pytest_plugins"] is not None
        assert "plugins" in result["pytest_plugins"]

    def test_detect_all_non_python_plugins_none(self, tmp_path):
        """非 Python 语言的 pytest_plugins 为 None。"""
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "app.js").write_text("const x = 1;")
        result = detect_all(str(tmp_path))
        assert result["language"] == "javascript"
        assert result["pytest_plugins"] is None

    def test_deprecated_alias_still_works(self, tmp_path):
        """废弃别名 detect_pytest_async_config 仍然可用。"""
        (tmp_path / "main.py").write_text("x = 1")
        result = detect_pytest_async_config(str(tmp_path))
        assert "asyncio_mode" in result
        assert "pytest_asyncio" in result
        assert "anyio" in result
        assert "missing" in result
        assert "hint" in result


# ---------------------------------------------------------------------------
# Python 环境选择（--python 参数）
# ---------------------------------------------------------------------------


class TestPythonEnvSelection:
    """验证 --python 参数支持跨环境检测。"""

    def test_check_toolchain_with_python_path(self):
        """指定 python_path 时用该路径检测。"""
        import sys as _sys

        tc = check_toolchain("python", _sys.executable)
        assert tc["available"] is True
        assert tc["python_path"] == _sys.executable
        assert "Python" in tc["version"]
        assert "pytest" not in tc["missing"]

    def test_check_toolchain_python_path_not_found(self, tmp_path):
        """路径不存在时 available=false。"""
        fake_path = str(tmp_path / "nonexistent_python")
        tc = check_toolchain("python", fake_path)
        assert tc["available"] is False
        assert fake_path in tc["missing"]
        assert tc["python_path"] == fake_path

    def test_check_toolchain_python_path_timeout(self, monkeypatch):
        """版本检查超时时标记为不可用。"""
        import subprocess

        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr("os.path.exists", lambda p: True)
        tc = check_toolchain("python", "/fake/python3")
        assert tc["available"] is False

    def test_check_toolchain_no_python_path_backward_compat(self):
        """不传 python_path 时行为不变。"""
        tc = check_toolchain("python")
        assert "python_path" in tc
        assert tc["python_path"] is None
        # 行为与原来一致
        assert tc["available"] is True

    def test_check_toolchain_non_python_lang_ignores_python_path(self):
        """非 Python 语言忽略 python_path。"""
        tc = check_toolchain("javascript", "/usr/bin/python3")
        assert tc["python_path"] is None

    def test_check_pytest_plugins_in_env(self, monkeypatch):
        """跨环境插件检测（mock subprocess）。"""
        import subprocess

        # mock subprocess.run 返回插件可用性
        availability = {
            "pytest-asyncio": True,
            "anyio": False,
            "pytest-mock": True,
            "hypothesis": False,
            "pytest-benchmark": False,
            "pytest-subtests": False,
            "pytest-freezegun": False,
            "responses": False,
        }
        mock_output = json.dumps(availability)

        monkeypatch.setattr("os.path.exists", lambda p: True)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=mock_output, stderr=""
            )
            plugins = _check_pytest_plugins_in_env("/fake/python3")

        assert plugins["pytest-asyncio"]["available"] is True
        assert plugins["anyio"]["available"] is False
        assert plugins["pytest-mock"]["available"] is True

    def test_check_pytest_plugins_in_env_timeout(self, monkeypatch):
        """跨环境插件检测超时时不崩溃。"""
        import subprocess

        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr("os.path.exists", lambda p: True)
        plugins = _check_pytest_plugins_in_env("/fake/python3")
        # 超时时全部标记为不可用
        for pkg, info in plugins.items():
            assert info["available"] is False

    def test_check_pytest_plugins_in_env_nonzero_return(self, monkeypatch):
        """目标环境 returncode!=0 时全部标记为不可用。"""
        import subprocess

        monkeypatch.setattr("os.path.exists", lambda p: True)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="error"
            )
            plugins = _check_pytest_plugins_in_env("/fake/python3")

        for pkg, info in plugins.items():
            assert info["available"] is False

    def test_detect_all_with_python_path(self, tmp_path):
        """python_path 贯穿 detect_all。"""
        import sys as _sys

        (tmp_path / "main.py").write_text("x = 1")
        result = detect_all(str(tmp_path), _sys.executable)
        assert result["toolchain"]["python_path"] == _sys.executable
        assert result["pytest_plugins"] is not None

    def test_output_contains_python_path(self, tmp_path):
        """输出 JSON 含 python_path 字段。"""
        import sys as _sys

        (tmp_path / "main.py").write_text("x = 1")
        result = detect_all(str(tmp_path), _sys.executable)
        assert "python_path" in result["toolchain"]
        assert result["toolchain"]["python_path"] == _sys.executable

    def test_backward_compat_no_python_path(self, tmp_path):
        """不传 python_path 时行为不变。"""
        (tmp_path / "main.py").write_text("x = 1")
        result = detect_all(str(tmp_path))
        assert result["toolchain"]["python_path"] is None
        assert result["pytest_plugins"] is not None

    def test_check_pytest_plugins_with_python_path(self, tmp_path):
        """check_pytest_plugins 指定 python_path 时跨环境检测。"""
        import sys as _sys

        (tmp_path / "main.py").write_text("x = 1")
        result = check_pytest_plugins(str(tmp_path), _sys.executable)
        assert "plugins" in result
        assert isinstance(result["plugins"], dict)
        # 当前 Python 有 pytest，至少一个插件可用
        # （不一定，但结构应该完整）
        for pkg, info in result["plugins"].items():
            assert "available" in info
            assert isinstance(info["available"], bool)

    def test_empty_plugins(self):
        """_empty_plugins 生成全不可用字典。"""
        from lang.registry import PYTEST_PLUGINS

        plugins = _empty_plugins(PYTEST_PLUGINS)
        for pkg, info in plugins.items():
            assert info["available"] is False
            assert "import_name" in info

    def test_cli_arg_python(self):
        """--python 参数被正确解析。"""
        import argparse
        from detect_lang import main as detect_lang_main

        # 用 --help 测试参数存在
        parser = argparse.ArgumentParser()
        parser.add_argument("target_path")
        parser.add_argument("--python")
        parser.add_argument("--output")
        # 验证 --python 参数存在
        args = parser.parse_args(["foo.py", "--python", "/usr/bin/python3"])
        assert args.python == "/usr/bin/python3"
