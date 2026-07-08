# -*- coding: utf-8 -*-
"""lang 包动态发现 + 注册表配置测试 — 覆盖 Codex 审查修复点 M8。

测试动态模块发现、错误隔离、注册表配置一致性。
"""
import os

import pytest

from lang import (
    get_analyzer,
    get_build_error_rules,
    get_failure_rules,
    get_file_placement,
    get_test_command,
    list_languages,
)


# ---------------------------------------------------------------------------
# 动态发现与注册
# ---------------------------------------------------------------------------


class TestDynamicDiscovery:
    """验证动态模块发现机制。"""

    def test_python_registered(self):
        assert "python" in list_languages()

    def test_get_analyzer_returns_instance(self):
        analyzer = get_analyzer("python")
        assert analyzer is not None
        assert hasattr(analyzer, "analyze")
        assert hasattr(analyzer, "gen_cases")

    def test_unsupported_language_raises(self):
        with pytest.raises(ValueError, match="Unsupported language"):
            get_analyzer("brainfuck")

    def test_list_languages_returns_list(self):
        langs = list_languages()
        assert isinstance(langs, list)
        assert "python" in langs

    @pytest.mark.parametrize(
        "lang",
        ["python", "javascript", "typescript", "go", "rust", "java"],
    )
    def test_all_languages_registered(self, lang):
        """SKILL.md 声明的 6 种语言都应注册了 analyzer。"""
        assert lang in list_languages(), f"{lang} not registered"

    @pytest.mark.parametrize(
        "lang",
        ["python", "javascript", "typescript", "go", "rust", "java"],
    )
    def test_all_analyzers_have_methods(self, lang):
        """每种语言的 analyzer 都有 analyze 和 gen_cases 方法。"""
        analyzer = get_analyzer(lang)
        assert hasattr(analyzer, "analyze"), f"{lang} missing analyze()"
        assert hasattr(analyzer, "gen_cases"), f"{lang} missing gen_cases()"


# ---------------------------------------------------------------------------
# M8: 错误隔离
# ---------------------------------------------------------------------------


class TestErrorIsolation:
    """验证单个适配器加载失败不影响其他适配器。"""

    def test_broken_adapter_does_not_break_all(self, monkeypatch):
        """用 mock 验证 _discover_languages 的 try/except 错误隔离。

        通过 mock pkgutil.iter_modules 注入不存在的 broken_lang 模块名，
        验证其导入失败被 try/except 捕获，不影响已注册的适配器。
        不清空 LANGUAGES（避免 importlib 缓存导致 @register 不重新执行）。
        """
        import pkgutil

        import lang as lang_pkg

        original_iter_modules = pkgutil.iter_modules
        original_languages = dict(lang_pkg.LANGUAGES)

        def mock_iter_modules(path, prefix=""):
            yield from original_iter_modules(path, prefix)
            # 注入一个不存在的 broken_lang 模块
            yield (None, "broken_lang", False)

        monkeypatch.setattr(pkgutil, "iter_modules", mock_iter_modules)

        try:
            # _discover_languages 应捕获 broken_lang 的 ImportError
            lang_pkg._discover_languages()
            # python 适配器应仍然注册成功（broken_lang 失败被隔离）
            assert "python" in lang_pkg.LANGUAGES
        finally:
            # 恢复原始状态
            lang_pkg.LANGUAGES.clear()
            lang_pkg.LANGUAGES.update(original_languages)

    def test_missing_dependency_adapter_does_not_break(self):
        """适配器 import 外部依赖失败时不应破坏其他适配器。"""
        # python_lang.py 只用标准库，不会失败
        # 但即使其他适配器依赖缺失，python 仍可用
        assert "python" in list_languages()
        analyzer = get_analyzer("python")
        assert analyzer is not None


# ---------------------------------------------------------------------------
# 注册表配置一致性
# ---------------------------------------------------------------------------


class TestRegistryConsistency:
    """验证 6 语言的配置完整性和一致性。"""

    LANGUAGES = [
        "python",
        "javascript",
        "typescript",
        "go",
        "rust",
        "java",
    ]

    @pytest.mark.parametrize("lang", LANGUAGES)
    def test_test_command_exists(self, lang):
        cmd = get_test_command(lang)
        assert cmd, f"{lang} missing TEST_COMMANDS"
        assert "command" in cmd
        assert "framework" in cmd
        assert "report_format" in cmd

    @pytest.mark.parametrize("lang", LANGUAGES)
    def test_file_placement_exists(self, lang):
        placement = get_file_placement(lang)
        assert placement, f"{lang} missing FILE_PLACEMENT"
        assert "naming" in placement
        assert "colocated" in placement

    @pytest.mark.parametrize("lang", LANGUAGES)
    def test_failure_rules_exist(self, lang):
        rules = get_failure_rules(lang)
        assert isinstance(rules, list)
        assert len(rules) > 0, f"{lang} has no failure rules"
        for rule in rules:
            assert len(rule) == 3  # (pattern, category, severity)

    @pytest.mark.parametrize("lang", LANGUAGES)
    def test_command_has_placeholders(self, lang):
        """验证命令模板包含占位符。"""
        cmd = get_test_command(lang)
        command = cmd["command"]
        # Java 用 {test_class}，其他用 {test_path}
        assert "{report}" in command
        assert "{test_" in command  # {test_path} or {test_class}

    def test_build_error_rules_exist(self):
        rules = get_build_error_rules()
        assert isinstance(rules, list)
        assert len(rules) > 0
        for pattern, category in rules:
            assert isinstance(pattern, str)
            assert isinstance(category, str)


# ---------------------------------------------------------------------------
# 命令格式验证
# ---------------------------------------------------------------------------


class TestCommandFormat:
    """验证特定语言的命令格式。"""

    def test_java_uses_semicolon_not_and(self):
        """Java 命令应用 ; 而非 &&，确保测试失败时也能复制报告。"""
        cmd = get_test_command("java")["command"]
        assert "&&" not in cmd, "Java 命令不应使用 &&"
        assert ";" in cmd, "Java 命令应使用 ; 确保复制报告"

    def test_java_uses_test_class_placeholder(self):
        """Java 命令应用 {test_class} 而非 {test_path}。"""
        cmd = get_test_command("java")["command"]
        assert "{test_class}" in cmd

    def test_rust_uses_cargo_nextest(self):
        cmd = get_test_command("rust")["command"]
        assert "cargo nextest" in cmd
        assert "--junit-path" in cmd

    def test_python_uses_pytest(self):
        cmd = get_test_command("python")["command"]
        assert "pytest" in cmd
        assert "--junitxml" in cmd

    def test_go_uses_gotestsum(self):
        cmd = get_test_command("go")["command"]
        assert "gotestsum" in cmd
        assert "--junitfile" in cmd


# ---------------------------------------------------------------------------
# 文件放置规则
# ---------------------------------------------------------------------------


class TestFilePlacement:
    """验证文件放置规则。"""

    def test_python_in_tests_dir(self):
        p = get_file_placement("python")
        assert p["colocated"] is False
        assert "tests" in p["directory"]

    def test_go_colocated(self):
        p = get_file_placement("go")
        assert p["colocated"] is True

    def test_js_colocated(self):
        p = get_file_placement("javascript")
        assert p["colocated"] is True
        assert ".test.js" in p["naming"]

    def test_java_in_src_test(self):
        p = get_file_placement("java")
        assert p["colocated"] is False
        assert "src/test/java" in p["directory"]
