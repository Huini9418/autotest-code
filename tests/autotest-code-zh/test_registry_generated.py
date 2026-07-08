# -*- coding: utf-8 -*-
"""registry.py 自动生成测试 — 由 auto_test skill 生成。

覆盖 5 个函数的等价类 + 边界值 + missing_plugin 规则验证。
"""
import pytest

from lang.registry import (
    TEST_COMMANDS,
    FILE_PLACEMENT,
    FAILURE_RULES,
    BUILD_ERROR_RULES,
    PYTEST_PLUGINS,
    get_test_command,
    get_failure_rules,
    get_file_placement,
    get_build_error_rules,
    get_pytest_plugins,
)


# ---------------------------------------------------------------------------
# get_test_command
# ---------------------------------------------------------------------------


class TestGetTestCommand:
    """验证 get_test_command 返回正确的命令配置。"""

    @pytest.mark.parametrize("lang", ["python", "javascript", "typescript",
                                       "go", "rust", "java"])
    def test_known_language_returns_dict(self, lang):
        """已知语言返回非空 dict。"""
        result = get_test_command(lang)
        assert isinstance(result, dict)
        assert "command" in result
        assert "framework" in result
        assert "report_format" in result

    def test_python_command_contains_pytest(self):
        result = get_test_command("python")
        assert "pytest" in result["command"]
        assert result["framework"] == "pytest"
        assert result["report_format"] == "junit_xml"
        assert result["needs_build"] is False

    def test_java_command_contains_mvn(self):
        result = get_test_command("java")
        assert "mvn" in result["command"]
        assert result["framework"] == "maven"
        assert result["needs_build"] is True

    def test_rust_needs_build(self):
        result = get_test_command("rust")
        assert result["needs_build"] is True

    def test_unknown_language_returns_empty_dict(self):
        """未知语言返回空 dict。"""
        assert get_test_command("brainfuck") == {}

    def test_empty_string_returns_empty_dict(self):
        """空字符串返回空 dict。"""
        assert get_test_command("") == {}


# ---------------------------------------------------------------------------
# get_failure_rules
# ---------------------------------------------------------------------------


class TestGetFailureRules:
    """验证 get_failure_rules 返回正确的失败分类规则。"""

    @pytest.mark.parametrize("lang", ["python", "javascript", "typescript",
                                       "go", "rust", "java"])
    def test_known_language_returns_list(self, lang):
        """已知语言返回非空列表。"""
        rules = get_failure_rules(lang)
        assert isinstance(rules, list)
        assert len(rules) > 0
        for rule in rules:
            assert len(rule) == 3  # (pattern, category, severity)

    def test_python_has_missing_plugin_rules(self):
        """Python 规则中包含 missing_plugin 分类。"""
        rules = get_failure_rules("python")
        categories = [r[1] for r in rules]
        assert "missing_plugin" in categories

    def test_python_missing_plugin_before_fixture_error(self):
        """missing_plugin 规则在 fixture_error 之前（优先匹配）。"""
        rules = get_failure_rules("python")
        missing_plugin_idx = None
        fixture_error_idx = None
        for i, (_, cat, _) in enumerate(rules):
            if cat == "missing_plugin":
                missing_plugin_idx = i
            if cat == "fixture_error":
                fixture_error_idx = i
        assert missing_plugin_idx is not None
        assert fixture_error_idx is not None
        assert missing_plugin_idx < fixture_error_idx

    def test_unknown_language_returns_empty_list(self):
        """未知语言返回空列表。"""
        assert get_failure_rules("brainfuck") == []

    def test_empty_string_returns_empty_list(self):
        assert get_failure_rules("") == []


# ---------------------------------------------------------------------------
# get_file_placement
# ---------------------------------------------------------------------------


class TestGetFilePlacement:
    """验证 get_file_placement 返回正确的文件放置规则。"""

    @pytest.mark.parametrize("lang", ["python", "javascript", "typescript",
                                       "go", "rust", "java"])
    def test_known_language_returns_dict(self, lang):
        """已知语言返回非空 dict。"""
        result = get_file_placement(lang)
        assert isinstance(result, dict)
        assert "directory" in result
        assert "naming" in result
        assert "colocated" in result

    def test_python_placement(self):
        result = get_file_placement("python")
        assert result["directory"] == "tests/"
        assert result["naming"] == "test_{name}.py"
        assert result["colocated"] is False

    def test_javascript_colocated(self):
        result = get_file_placement("javascript")
        assert result["colocated"] is True

    def test_unknown_language_returns_empty_dict(self):
        assert get_file_placement("brainfuck") == {}


# ---------------------------------------------------------------------------
# get_build_error_rules
# ---------------------------------------------------------------------------


class TestGetBuildErrorRules:
    """验证 get_build_error_rules 返回编译错误规则。"""

    def test_returns_non_empty_list(self):
        """返回非空列表。"""
        rules = get_build_error_rules()
        assert isinstance(rules, list)
        assert len(rules) > 0

    def test_each_rule_has_pattern_and_category(self):
        """每条规则有 pattern 和 category。"""
        for pattern, category in get_build_error_rules():
            assert isinstance(pattern, str)
            assert isinstance(category, str)

    def test_contains_rust_error_pattern(self):
        """包含 Rust 编译错误模式。"""
        rules = get_build_error_rules()
        categories = [cat for _, cat in rules]
        assert "rust_compile_error" in categories

    def test_contains_java_error_pattern(self):
        """包含 Java 编译错误模式。"""
        rules = get_build_error_rules()
        categories = [cat for _, cat in rules]
        assert "java_compile_error" in categories


# ---------------------------------------------------------------------------
# get_pytest_plugins
# ---------------------------------------------------------------------------


class TestGetPytestPlugins:
    """验证 get_pytest_plugins 返回插件声明表。"""

    def test_returns_non_empty_dict(self):
        """返回非空 dict。"""
        plugins = get_pytest_plugins()
        assert isinstance(plugins, dict)
        assert len(plugins) > 0

    def test_contains_eight_plugins(self):
        """包含 8 个插件。"""
        plugins = get_pytest_plugins()
        assert len(plugins) == 8

    @pytest.mark.parametrize("pkg_name", [
        "pytest-asyncio", "anyio", "pytest-mock", "hypothesis",
        "pytest-benchmark", "pytest-subtests", "pytest-freezegun", "responses",
    ])
    def test_plugin_exists(self, pkg_name):
        """每个预期的插件都在表中。"""
        plugins = get_pytest_plugins()
        assert pkg_name in plugins

    @pytest.mark.parametrize("pkg_name", [
        "pytest-asyncio", "anyio", "pytest-mock", "hypothesis",
        "pytest-benchmark", "pytest-subtests", "pytest-freezegun", "responses",
    ])
    def test_plugin_has_required_fields(self, pkg_name):
        """每个插件条目含必需字段。"""
        plugins = get_pytest_plugins()
        info = plugins[pkg_name]
        assert "import_name" in info
        assert "trigger_type" in info
        assert "trigger" in info
        assert "error_pattern" in info
        assert "alt" in info

    def test_fixture_type_plugins(self):
        """fixture 型插件的 trigger_type 为 fixture。"""
        plugins = get_pytest_plugins()
        fixture_plugins = [
            pkg for pkg, info in plugins.items()
            if info["trigger_type"] == "fixture"
        ]
        assert "pytest-mock" in fixture_plugins
        assert "pytest-benchmark" in fixture_plugins
        assert "pytest-subtests" in fixture_plugins
        assert "pytest-freezegun" in fixture_plugins

    def test_import_type_plugins(self):
        """import 型插件的 trigger_type 为 marker 或 decorator。"""
        plugins = get_pytest_plugins()
        import_plugins = [
            pkg for pkg, info in plugins.items()
            if info["trigger_type"] in ("marker", "decorator")
        ]
        assert "pytest-asyncio" in import_plugins
        assert "anyio" in import_plugins
        assert "hypothesis" in import_plugins
        assert "responses" in import_plugins
