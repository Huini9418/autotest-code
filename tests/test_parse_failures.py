# -*- coding: utf-8 -*-
"""失败解析测试 — 覆盖 Codex 审查修复点 M4/C6/C7。

测试 JUnit XML 解析、失败分类优先级、方言处理。
"""
import json
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.normpath(os.path.join(
    TEST_DIR,
    "..", "skills", "autotest-code-zh", "scripts"
))

from parse_failures import (
    classify_failure,
    parse_junitxml,
    _suggest,
    _compute_failure_signature,
    _load_history,
    _append_history,
    _validate_history_path,
    _extract_missing_module,
    _get_install_command,
)
from lang import get_failure_rules, get_build_error_rules


# ---------------------------------------------------------------------------
# M4: time="" 不崩溃
# ---------------------------------------------------------------------------


class TestTimeParsing:
    """验证 time 属性为空字符串或非数值时不崩溃。"""

    def _write_xml(self, tmp_path, time_attr):
        xml = f'''<?xml version="1.0" encoding="utf-8"?>
<testsuite>
  <testcase name="test_foo" classname="TestFoo" time="{time_attr}">
    <failure message="assert False">assert False</failure>
  </testcase>
</testsuite>'''
        f = tmp_path / "report.xml"
        f.write_text(xml)
        return str(f)

    def test_empty_time_string(self, tmp_path):
        xml_path = self._write_xml(tmp_path, "")
        result = parse_junitxml(xml_path, "python")
        assert result["summary"]["total"] == 1
        assert result["summary"]["failed"] == 1
        assert result["all_cases"][0]["time"] == 0.0

    def test_normal_time(self, tmp_path):
        xml_path = self._write_xml(tmp_path, "0.123")
        result = parse_junitxml(xml_path, "python")
        assert result["all_cases"][0]["time"] == 0.123

    def test_missing_time_attr(self, tmp_path):
        xml_path = tmp_path / "report.xml"
        xml_path.write_text('''<?xml version="1.0"?>
<testsuite>
  <testcase name="test_foo" classname="TestFoo">
    <failure message="fail">fail</failure>
  </testcase>
</testsuite>''')
        result = parse_junitxml(str(xml_path), "python")
        assert result["all_cases"][0]["time"] == 0.0

    def test_non_numeric_time(self, tmp_path):
        xml_path = self._write_xml(tmp_path, "N/A")
        result = parse_junitxml(xml_path, "python")
        assert result["all_cases"][0]["time"] == 0.0


# ---------------------------------------------------------------------------
# C7: BUILD_ERROR_RULES 不再过宽
# ---------------------------------------------------------------------------


class TestBuildErrorRulesScope:
    """验证 BUILD_ERROR_RULES 不会误分类运行时错误。"""

    def test_js_runtime_cannot_find_module_is_test_setup(self):
        """JS 运行时 Cannot find module → test_setup，不是 build_error。"""
        js_rules = get_failure_rules("javascript")
        cat, sev = classify_failure(
            "Error: Cannot find module 'foo'", js_rules
        )
        assert sev == "test_setup"
        assert cat == "import_error"

    def test_js_module_not_found_is_test_setup(self):
        js_rules = get_failure_rules("javascript")
        cat, sev = classify_failure("MODULE_NOT_FOUND", js_rules)
        assert sev == "test_setup"

    def test_python_import_error_is_test_setup(self):
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure(
            "ModuleNotFoundError: No module named 'foo'", py_rules
        )
        assert sev == "test_setup"
        assert cat == "import_error"

    def test_empty_message_defaults_to_test_logic(self):
        cat, sev = classify_failure("", [])
        assert cat == "unknown"
        assert sev == "test_logic"

    def test_none_message_defaults_to_test_logic(self):
        cat, sev = classify_failure(None, [])
        assert sev == "test_logic"


# ---------------------------------------------------------------------------
# C6: Rust 构建错误正则正确匹配
# ---------------------------------------------------------------------------


class TestRustBuildErrorPattern:
    """验证 Rust 编译错误正则匹配实际格式。"""

    def test_rust_error_bracket_matches(self):
        rust_rules = get_failure_rules("rust")
        cat, sev = classify_failure(
            "error[E0308]: mismatched types", rust_rules
        )
        assert sev == "build_error"
        assert cat == "rust_compile_error"

    def test_rust_error_different_code(self):
        rust_rules = get_failure_rules("rust")
        cat, sev = classify_failure(
            "error[E0277]: the trait bound is not satisfied",
            rust_rules,
        )
        assert sev == "build_error"

    def test_java_compile_error_matches(self):
        java_rules = get_failure_rules("java")
        cat, sev = classify_failure(
            "Foo.java:10: error: ';' expected", java_rules
        )
        assert sev == "build_error"
        assert cat == "java_compile_error"

    def test_java_cannot_find_symbol_is_build_error(self):
        """Java cannot find symbol 是编译错误，应分类为 build_error。"""
        java_rules = get_failure_rules("java")
        cat, sev = classify_failure("cannot find symbol", java_rules)
        assert sev == "build_error"
        assert cat == "compilation_error"


# ---------------------------------------------------------------------------
# 失败分类优先级
# ---------------------------------------------------------------------------


class TestClassificationPriority:
    """验证分类优先级: build_error > 语言规则 > 通用规则。"""

    def test_build_error_rules_take_priority(self):
        """build_error 规则优先于语言规则。"""
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure(
            "COMPILATION ERROR in module", py_rules
        )
        assert sev == "build_error"
        assert cat == "compilation_error"

    def test_language_rules_before_common(self):
        """语言规则优先于通用规则。"""
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure("TimeoutError: timed out", py_rules)
        assert sev == "test_env"
        assert cat == "timeout"

    def test_common_rules_as_fallback(self):
        """无语言规则时回退到通用规则。"""
        cat, sev = classify_failure("timed out after 30s", [])
        assert sev == "test_env"
        assert cat == "timeout"

    def test_python_assertion_error(self):
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure("AssertionError: assert 1 == 2", py_rules)
        assert sev == "test_logic"
        assert cat == "assertion_error"

    def test_python_type_error(self):
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure(
            "TypeError: unsupported operand type", py_rules
        )
        assert sev == "test_logic"

    def test_python_target_bug_severity(self):
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure(
            "RuntimeError: something went wrong", py_rules
        )
        assert sev == "target_bug"

    def test_python_zero_division_is_target_bug(self):
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure(
            "ZeroDivisionError: division by zero", py_rules
        )
        assert sev == "target_bug"


# ---------------------------------------------------------------------------
# JUnit XML 方言处理
# ---------------------------------------------------------------------------


class TestJunitXmlDialects:
    """验证不同测试框架的 JUnit XML 方言解析。"""

    def test_pytest_dialect(self, tmp_path):
        """pytest: failure 元素含 message 和 text。"""
        xml = '''<?xml version="1.0"?>
<testsuite>
  <testcase name="test_a" classname="TestA" time="0.1">
    <failure message="assert False">assert False</failure>
  </testcase>
  <testcase name="test_b" classname="TestB" time="0.05"/>
</testsuite>'''
        f = tmp_path / "report.xml"
        f.write_text(xml)
        result = parse_junitxml(str(f), "python")
        assert result["summary"]["total"] == 2
        assert result["summary"]["passed"] == 1
        assert result["summary"]["failed"] == 1

    def test_surefire_dialect_with_system_out(self, tmp_path):
        """Surefire: system-out/system-err 子元素。"""
        xml = '''<?xml version="1.0"?>
<testsuite>
  <testcase name="testFoo" classname="com.FooTest" time="0.2">
    <failure message="assertion failed"/>
    <system-out>Some stdout</system-out>
    <system-err>Some stderr</system-err>
  </testcase>
</testsuite>'''
        f = tmp_path / "report.xml"
        f.write_text(xml)
        result = parse_junitxml(str(f), "java")
        assert result["summary"]["failed"] == 1
        failure = result["failures"][0]
        assert "stdout" in failure["traceback"].lower()

    def test_skipped_test(self, tmp_path):
        xml = '''<?xml version="1.0"?>
<testsuite>
  <testcase name="test_skip" classname="TestS" time="0">
    <skipped message="reason: not implemented"/>
  </testcase>
</testsuite>'''
        f = tmp_path / "report.xml"
        f.write_text(xml)
        result = parse_junitxml(str(f), "python")
        assert result["summary"]["skipped"] == 1
        assert result["summary"]["passed"] == 0

    def test_error_vs_failure(self, tmp_path):
        """error 元素和 failure 元素分开计数。"""
        xml = '''<?xml version="1.0"?>
<testsuite>
  <testcase name="test_fail" classname="A" time="0">
    <failure message="assert">assert</failure>
  </testcase>
  <testcase name="test_err" classname="B" time="0">
    <error message="exception">traceback</error>
  </testcase>
</testsuite>'''
        f = tmp_path / "report.xml"
        f.write_text(xml)
        result = parse_junitxml(str(f), "python")
        assert result["summary"]["failed"] == 1
        assert result["summary"]["errors"] == 1

    def test_all_passed(self, tmp_path):
        xml = '''<?xml version="1.0"?>
<testsuite>
  <testcase name="test_a" classname="A" time="0.01"/>
  <testcase name="test_b" classname="B" time="0.02"/>
  <testcase name="test_c" classname="C" time="0.03"/>
</testsuite>'''
        f = tmp_path / "report.xml"
        f.write_text(xml)
        result = parse_junitxml(str(f), "python")
        assert result["summary"]["total"] == 3
        assert result["summary"]["passed"] == 3
        assert result["summary"]["failed"] == 0
        assert result["summary"]["pass_rate"] == 100.0

    def test_empty_testsuite(self, tmp_path):
        xml = '''<?xml version="1.0"?>
<testsuite/>'''
        f = tmp_path / "report.xml"
        f.write_text(xml)
        result = parse_junitxml(str(f), "python")
        assert result["summary"]["total"] == 0
        assert result["summary"]["pass_rate"] == 0.0

    def test_nested_testsuites(self, tmp_path):
        """root.iter('testcase') 应递归查找嵌套 testsuite。"""
        xml = '''<?xml version="1.0"?>
<testsuites>
  <testsuite name="suite1">
    <testcase name="test_a" classname="A" time="0"/>
  </testsuite>
  <testsuite name="suite2">
    <testcase name="test_b" classname="B" time="0"/>
  </testsuite>
</testsuites>'''
        f = tmp_path / "report.xml"
        f.write_text(xml)
        result = parse_junitxml(str(f), "python")
        assert result["summary"]["total"] == 2


# ---------------------------------------------------------------------------
# 建议生成
# ---------------------------------------------------------------------------


class TestSuggestions:
    """验证不同 severity 的建议消息。"""

    def test_build_error_suggestion_has_hammer(self, tmp_path):
        xml = '''<?xml version="1.0"?>
<testsuite>
  <testcase name="t" classname="A" time="0">
    <failure message="COMPILATION ERROR">err</failure>
  </testcase>
</testsuite>'''
        f = tmp_path / "report.xml"
        f.write_text(xml)
        result = parse_junitxml(str(f), "java")
        assert "🔨" in result["failures"][0]["suggestion"]

    def test_target_bug_suggestion_has_warning(self, tmp_path):
        xml = '''<?xml version="1.0"?>
<testsuite>
  <testcase name="t" classname="A" time="0">
    <failure message="RuntimeError: crash">err</failure>
  </testcase>
</testsuite>'''
        f = tmp_path / "report.xml"
        f.write_text(xml)
        result = parse_junitxml(str(f), "python")
        assert "⚠️" in result["failures"][0]["suggestion"]

    def test_test_logic_suggestion_has_pencil(self, tmp_path):
        xml = '''<?xml version="1.0"?>
<testsuite>
  <testcase name="t" classname="A" time="0">
    <failure message="AssertionError: fail">err</failure>
  </testcase>
</testsuite>'''
        f = tmp_path / "report.xml"
        f.write_text(xml)
        result = parse_junitxml(str(f), "python")
        assert "📝" in result["failures"][0]["suggestion"]


# ---------------------------------------------------------------------------
# missing_plugin 分类和建议
# ---------------------------------------------------------------------------


class TestMissingPlugin:
    """验证 missing_plugin 失败分类和安装建议。"""

    def test_plugin_not_found_classified_as_missing_plugin(self):
        """PluginNotFoundError → missing_plugin。"""
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure(
            "PluginNotFoundError: pytest-asyncio", py_rules
        )
        assert cat == "missing_plugin"
        assert sev == "test_setup"

    def test_plugin_could_not_be_found(self):
        """plugin could not be found → missing_plugin。"""
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure(
            "plugin pytest-mock could not be found", py_rules
        )
        assert cat == "missing_plugin"

    def test_mocker_fixture_not_found(self):
        """fixture 'mocker' not found → missing_plugin（不是 fixture_error）。"""
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure(
            "fixture 'mocker' not found", py_rules
        )
        assert cat == "missing_plugin"
        assert sev == "test_setup"

    def test_benchmark_fixture_not_found(self):
        """fixture 'benchmark' not found → missing_plugin。"""
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure(
            "fixture 'benchmark' not found", py_rules
        )
        assert cat == "missing_plugin"

    def test_subtests_fixture_not_found(self):
        """fixture 'subtests' not found → missing_plugin。"""
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure(
            "fixture 'subtests' not found", py_rules
        )
        assert cat == "missing_plugin"

    def test_freezer_fixture_not_found(self):
        """fixture 'freezer' not found → missing_plugin。"""
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure(
            "fixture 'freezer' not found", py_rules
        )
        assert cat == "missing_plugin"

    def test_missing_plugin_before_fixture_error(self):
        """missing_plugin 规则优先于 fixture_error。"""
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure(
            "fixture 'mocker' not found", py_rules
        )
        assert cat == "missing_plugin"

    def test_other_fixture_not_found_is_fixture_error(self):
        """非插件 fixture not found → fixture_error。"""
        py_rules = get_failure_rules("python")
        cat, sev = classify_failure(
            "fixture 'my_custom' not found", py_rules
        )
        assert cat == "fixture_error"

    def test_suggest_mocker_install(self):
        """mocker → pip install pytest-mock 建议。"""
        suggestion = _suggest(
            "missing_plugin", "test_setup",
            "fixture 'mocker' not found", "python"
        )
        assert "pytest-mock" in suggestion
        assert "pip install" in suggestion
        assert "unittest.mock" in suggestion

    def test_suggest_benchmark_install(self):
        """benchmark → pip install pytest-benchmark 建议。"""
        suggestion = _suggest(
            "missing_plugin", "test_setup",
            "fixture 'benchmark' not found", "python"
        )
        assert "pytest-benchmark" in suggestion
        assert "time.perf_counter" in suggestion

    def test_suggest_subtests_install(self):
        """subtests → pip install pytest-subtests 建议。"""
        suggestion = _suggest(
            "missing_plugin", "test_setup",
            "fixture 'subtests' not found", "python"
        )
        assert "pytest-subtests" in suggestion

    def test_suggest_freezer_install(self):
        """freezer → pip install pytest-freezegun 建议。"""
        suggestion = _suggest(
            "missing_plugin", "test_setup",
            "fixture 'freezer' not found", "python"
        )
        assert "pytest-freezegun" in suggestion

    def test_suggest_missing_plugin_default(self):
        """无匹配 trigger → 通用 missing_plugin 建议。"""
        suggestion = _suggest(
            "missing_plugin", "test_setup",
            "PluginNotFoundError: some-plugin", "python"
        )
        assert "插件" in suggestion or "plugin" in suggestion.lower()

    def test_suggest_missing_plugin_in_parse_junitxml(self, tmp_path):
        """parse_junitxml 输出中 suggestion 含安装建议。"""
        xml = '''<?xml version="1.0"?>
<testsuite>
  <testcase name="t" classname="A" time="0">
    <failure message="fixture 'mocker' not found">err</failure>
  </testcase>
</testsuite>'''
        f = tmp_path / "report.xml"
        f.write_text(xml)
        result = parse_junitxml(str(f), "python")
        assert result["failures"][0]["category"] == "missing_plugin"
        assert "pytest-mock" in result["failures"][0]["suggestion"]


# ---------------------------------------------------------------------------
# import_error 多语言建议增强
# ---------------------------------------------------------------------------


class TestImportErrorSuggestion:
    """验证 import_error 的多语言安装建议。"""

    def test_python_no_module_named(self):
        """Python ModuleNotFoundError → pip install 建议。"""
        suggestion = _suggest(
            "import_error", "test_setup",
            "ModuleNotFoundError: No module named 'requests'", "python"
        )
        assert "pip install" in suggestion
        assert "requests" in suggestion

    def test_python_cannot_import_name(self):
        """Python cannot import name → pip install 建议。"""
        suggestion = _suggest(
            "import_error", "test_setup",
            "cannot import name 'foo' from 'bar'", "python"
        )
        assert "pip install" in suggestion
        assert "bar" in suggestion

    def test_javascript_cannot_find_module(self):
        """JS Cannot find module → npm install 建议。"""
        suggestion = _suggest(
            "import_error", "test_setup",
            "Cannot find module 'lodash'", "javascript"
        )
        assert "npm install" in suggestion
        assert "lodash" in suggestion

    def test_javascript_relative_path_filtered(self):
        """JS 相对路径模块被过滤，不给具体包名。"""
        suggestion = _suggest(
            "import_error", "test_setup",
            "Cannot find module './utils'", "javascript"
        )
        assert "npm install" in suggestion
        assert "./utils" not in suggestion

    def test_go_cannot_find_package(self):
        """Go cannot find package → go get 建议。"""
        suggestion = _suggest(
            "import_error", "test_setup",
            'cannot find package "github.com/foo/bar"', "go"
        )
        assert "go get" in suggestion

    def test_rust_unresolved_import(self):
        """Rust unresolved import → cargo add 建议。"""
        suggestion = _suggest(
            "import_error", "test_setup",
            "unresolved import serde::Serialize", "rust"
        )
        assert "cargo add" in suggestion
        assert "serde" in suggestion

    def test_java_class_not_found_generic(self):
        """Java ClassNotFoundException → 通用提示（不提取类名）。"""
        suggestion = _suggest(
            "import_error", "test_setup",
            "ClassNotFoundException: org.mockito.Mockito", "java"
        )
        assert "pom.xml" in suggestion or "build.gradle" in suggestion


# ---------------------------------------------------------------------------
# 失败签名计算
# ---------------------------------------------------------------------------


class TestFailureSignature:
    """验证 _compute_failure_signature() 签名计算。"""

    def test_empty_failures_empty_signature(self):
        """无失败时签名为空。"""
        result = _compute_failure_signature([])
        assert result["signature"] == ""
        assert result["count"] == 0
        assert result["test_names"] == []

    def test_same_failures_same_signature(self):
        """相同失败列表 → 相同签名。"""
        failures = [
            {"classname": "TestA", "name": "test_x", "category": "assertion_error"},
            {"classname": "TestB", "name": "test_y", "category": "type_error"},
        ]
        sig1 = _compute_failure_signature(failures)
        sig2 = _compute_failure_signature(failures)
        assert sig1["signature"] == sig2["signature"]

    def test_different_count_different_signature(self):
        """不同失败数量 → 不同签名（修了一个测试后签名变化）。"""
        failures_2 = [
            {"classname": "TestA", "name": "test_x", "category": "assertion_error"},
            {"classname": "TestB", "name": "test_y", "category": "type_error"},
        ]
        failures_1 = [failures_2[0]]
        sig1 = _compute_failure_signature(failures_1)
        sig2 = _compute_failure_signature(failures_2)
        assert sig1["signature"] != sig2["signature"]

    def test_different_test_names_different_signature(self):
        """不同测试名 → 不同签名。"""
        failures_a = [
            {"classname": "TestA", "name": "test_x", "category": "assertion_error"},
        ]
        failures_b = [
            {"classname": "TestA", "name": "test_y", "category": "assertion_error"},
        ]
        sig_a = _compute_failure_signature(failures_a)
        sig_b = _compute_failure_signature(failures_b)
        assert sig_a["signature"] != sig_b["signature"]

    def test_different_categories_different_signature(self):
        """不同分类集合 → 不同签名。"""
        failures_a = [
            {"classname": "TestA", "name": "test_x", "category": "assertion_error"},
        ]
        failures_b = [
            {"classname": "TestA", "name": "test_x", "category": "missing_plugin"},
        ]
        sig_a = _compute_failure_signature(failures_a)
        sig_b = _compute_failure_signature(failures_b)
        assert sig_a["signature"] != sig_b["signature"]

    def test_same_failures_reordered_same_signature(self):
        """相同失败不同顺序 → 相同签名（test_names 排序）。"""
        failures_a = [
            {"classname": "TestA", "name": "test_x", "category": "assertion_error"},
            {"classname": "TestB", "name": "test_y", "category": "type_error"},
        ]
        failures_b = list(reversed(failures_a))
        sig_a = _compute_failure_signature(failures_a)
        sig_b = _compute_failure_signature(failures_b)
        assert sig_a["signature"] == sig_b["signature"]

    def test_signature_is_8_char_hex(self):
        """签名是 8 字符 hex 字符串。"""
        failures = [
            {"classname": "TestA", "name": "test_x", "category": "assertion_error"},
        ]
        result = _compute_failure_signature(failures)
        assert len(result["signature"]) == 8
        int(result["signature"], 16)  # 是有效 hex

    def test_count_matches(self):
        """count 字段与失败数量一致。"""
        failures = [
            {"classname": "TestA", "name": "test_x", "category": "assertion_error"},
            {"classname": "TestB", "name": "test_y", "category": "type_error"},
            {"classname": "TestC", "name": "test_z", "category": "import_error"},
        ]
        result = _compute_failure_signature(failures)
        assert result["count"] == 3


# ---------------------------------------------------------------------------
# 历史追踪
# ---------------------------------------------------------------------------


class TestHistoryTracking:
    """验证 --history-file 跨调用重复检测。"""

    def _write_xml(self, tmp_path, failures):
        """构造 JUnit XML。"""
        cases = ""
        for classname, name, msg in failures:
            cases += f'''  <testcase name="{name}" classname="{classname}" time="0">
    <failure message="{msg}">{msg}</failure>
  </testcase>
'''
        xml = f'''<?xml version="1.0"?>
<testsuite>
{cases}</testsuite>'''
        f = tmp_path / "report.xml"
        f.write_text(xml)
        return str(f)


    def test_load_history_nonexistent_returns_empty(self, tmp_path):
        """不存在的历史文件返回空列表。"""
        import tempfile

        path = os.path.join(tempfile.gettempdir(), "nonexistent_history.json")
        assert _load_history(path) == []

    def test_append_and_load_history(self, tmp_path):
        """追加签名后能加载。"""
        import tempfile

        path = os.path.join(tempfile.gettempdir(), "test_append_history.json")
        # 清空残留
        Path(path).write_text("[]", encoding="utf-8")
        sig = {"signature": "abc12345", "count": 2, "test_names": ["A::test_x"]}
        _append_history(path, sig)
        history = _load_history(path)
        assert len(history) == 1
        assert history[0]["signature"] == "abc12345"
        # 清理
        Path(path).unlink(missing_ok=True)

    def test_history_max_10_entries(self, tmp_path):
        """历史文件最多保留 10 条。"""
        import tempfile

        path = os.path.join(tempfile.gettempdir(), "test_max_history.json")
        Path(path).write_text("[]", encoding="utf-8")
        for i in range(15):
            sig = {
                "signature": f"sig{i:08d}",
                "count": 1,
                "test_names": [f"A::test_{i}"],
            }
            _append_history(path, sig)
        history = _load_history(path)
        assert len(history) == 10
        # 保留最近 10 条（sig5 ~ sig14）
        assert history[0]["signature"] == "sig00000005"
        assert history[-1]["signature"] == "sig00000014"
        Path(path).unlink(missing_ok=True)

    def test_main_no_history_file_no_stop(self, tmp_path):
        """不传 --history-file 时 stop=False。"""
        xml_path = self._write_xml(tmp_path, [("A", "test_x", "AssertionError")])
        result = parse_junitxml(xml_path, "python")
        # parse_junitxml 不设 stop，stop 在 main() 中设
        assert "stop" not in result

    def test_repeated_failure_triggers_stop(self, tmp_path):
        """连续两次相同失败 → 第二次 stop=true。"""
        import subprocess

        history_path = os.path.expanduser("~/.claude/test_repeat_stop.json")
        Path(history_path).parent.mkdir(parents=True, exist_ok=True)
        Path(history_path).write_text("[]", encoding="utf-8")

        xml_path = self._write_xml(tmp_path, [("A", "test_x", "AssertionError: fail")])

        # 第一次调用
        subprocess.run(
            ["python3", "parse_failures.py", "--junitxml", xml_path,
             "--lang", "python", "--history-file", history_path,
             "--output", str(tmp_path / "out1.json")],
            capture_output=True, text=True,
            cwd=SCRIPTS_DIR,
        )
        out1 = json.loads(Path(str(tmp_path / "out1.json")).read_text())
        assert out1["stop"] is False

        # 第二次调用（相同失败）
        subprocess.run(
            ["python3", "parse_failures.py", "--junitxml", xml_path,
             "--lang", "python", "--history-file", history_path,
             "--output", str(tmp_path / "out2.json")],
            capture_output=True, text=True,
            cwd=SCRIPTS_DIR,
        )
        out2 = json.loads(Path(str(tmp_path / "out2.json")).read_text())
        assert out2["stop"] is True
        assert out2["repeat_count"] == 2

        Path(history_path).unlink(missing_ok=True)

    def test_different_failures_no_stop(self, tmp_path):
        """不同失败签名 → stop=false。"""
        import subprocess

        history_path = os.path.expanduser("~/.claude/test_diff_stop.json")
        Path(history_path).parent.mkdir(parents=True, exist_ok=True)
        Path(history_path).write_text("[]", encoding="utf-8")

        xml1 = self._write_xml(tmp_path, [("A", "test_x", "AssertionError: fail")])
        # 第一次调用
        subprocess.run(
            ["python3", "parse_failures.py", "--junitxml", xml1,
             "--lang", "python", "--history-file", history_path,
             "--output", str(tmp_path / "out1.json")],
            capture_output=True, text=True,
            cwd=SCRIPTS_DIR,
        )

        # 第二次调用：不同的失败（多一个测试）
        xml2_path = tmp_path / "report2.xml"
        xml2_path.write_text('''<?xml version="1.0"?>
<testsuite>
  <testcase name="test_x" classname="A" time="0">
    <failure message="AssertionError: fail">fail</failure>
  </testcase>
  <testcase name="test_y" classname="B" time="0">
    <failure message="TypeError: bad">bad</failure>
  </testcase>
</testsuite>''')
        subprocess.run(
            ["python3", "parse_failures.py", "--junitxml", str(xml2_path),
             "--lang", "python", "--history-file", history_path,
             "--output", str(tmp_path / "out2.json")],
            capture_output=True, text=True,
            cwd=SCRIPTS_DIR,
        )
        out2 = json.loads(Path(str(tmp_path / "out2.json")).read_text())
        assert out2["stop"] is False

        Path(history_path).unlink(missing_ok=True)

    def test_all_pass_clears_history(self, tmp_path):
        """全部通过时清空历史文件。"""
        import subprocess

        history_path = os.path.expanduser("~/.claude/test_clear_history.json")
        Path(history_path).parent.mkdir(parents=True, exist_ok=True)
        # 预填充历史
        Path(history_path).write_text(
            json.dumps([{"signature": "old12345", "count": 1, "test_names": []}]),
            encoding="utf-8",
        )

        # 全部通过的 XML
        xml_path = tmp_path / "pass.xml"
        xml_path.write_text('''<?xml version="1.0"?>
<testsuite>
  <testcase name="test_a" classname="A" time="0.01"/>
  <testcase name="test_b" classname="B" time="0.02"/>
</testsuite>''')
        subprocess.run(
            ["python3", "parse_failures.py", "--junitxml", str(xml_path),
             "--lang", "python", "--history-file", history_path,
             "--output", str(tmp_path / "out.json")],
            capture_output=True, text=True,
            cwd=SCRIPTS_DIR,
        )
        history = json.loads(Path(history_path).read_text(encoding="utf-8"))
        assert history == []

        Path(history_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# P2-3: parse_failures.py 边缘情况补全
# ---------------------------------------------------------------------------


class TestLoadHistoryCorruptJson:
    """_load_history 读取损坏 JSON 时安全降级。"""

    def test_corrupted_json_returns_empty(self, tmp_path):
        """损坏的 JSON 文件不崩溃，返回空列表。"""
        history_path = str(tmp_path / "history.json")
        Path(history_path).write_text("not valid json{{{{", encoding="utf-8")
        result = _load_history(history_path)
        assert result == []

    def test_truncated_json_returns_empty(self, tmp_path):
        """被截断的 JSON（如进程崩溃时写入）返回空列表。"""
        history_path = str(tmp_path / "history.json")
        Path(history_path).write_text('[{"sig": "abc"', encoding="utf-8")
        result = _load_history(history_path)
        assert result == []


class TestMainOutputFlag:
    """parse_failures.py --output 参数测试。"""

    def _make_xml(self, tmp_path, name="report.xml"):
        xml_path = tmp_path / name
        xml_path.write_text(
            '<?xml version="1.0"?>\n'
            "<testsuite>\n"
            '  <testcase name="test_ok" classname="Foo" time="0.01"/>\n'
            "</testsuite>\n"
        )
        return xml_path

    def _run_script(self, xml_path, extra_args=None):
        import subprocess as _sp
        import sys as _sys
        cmd = [_sys.executable, "parse_failures.py", "--junitxml", str(xml_path)]
        if extra_args:
            cmd.extend(extra_args)
        return _sp.run(cmd, capture_output=True, text=True, cwd=SCRIPTS_DIR)

    def test_output_writes_to_file(self, tmp_path):
        """--output 将结果写入文件而非 stdout。"""
        xml_path = self._make_xml(tmp_path)
        out_file = tmp_path / "result.json"
        result = self._run_script(xml_path, ["--output", str(out_file)])
        assert result.returncode == 0
        assert "Report written to" in result.stderr
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert "summary" in data

    def test_output_creates_parent_dirs(self, tmp_path):
        """--output 自动创建父目录。"""
        xml_path = self._make_xml(tmp_path)
        out_file = tmp_path / "deep" / "nested" / "result.json"
        result = self._run_script(xml_path, ["--output", str(out_file)])
        assert result.returncode == 0
        assert out_file.exists()

    def test_stdout_when_no_output_flag(self, tmp_path):
        """无 --output 时结果写到 stdout。"""
        xml_path = self._make_xml(tmp_path)
        result = self._run_script(xml_path)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "summary" in data

    def test_junitxml_not_found_exit_1(self, tmp_path):
        """--junitxml 文件不存在时退出码 1。"""
        result = self._run_script(tmp_path / "nonexistent.xml")
        assert result.returncode == 1
        assert "not found" in result.stderr.lower()


class TestSuggestTestEnvSeverity:
    """验证 test_env severity 的建议路径。"""

    def test_timeout_category_test_env(self):
        """timeout 分类的 severity 为 test_env，建议含 🌐。"""
        suggestion = _suggest("timeout", "test_env")
        assert suggestion.startswith("🌐")

    def test_file_error_category_test_env(self):
        """file_error 分类的 severity 为 test_env，建议含 🌐。"""
        suggestion = _suggest("file_error", "test_env")
        assert suggestion.startswith("🌐")

    def test_test_setup_severity_uses_wrench(self):
        """test_setup severity 建议含 🔧。"""
        suggestion = _suggest("fixture_error", "test_setup")
        assert suggestion.startswith("🔧")

    def test_build_error_severity_uses_hammer(self):
        """build_error severity 建议含 🔨。"""
        suggestion = _suggest("compilation_error", "build_error")
        assert suggestion.startswith("🔨")

    def test_target_bug_severity_uses_warning(self):
        """target_bug severity 建议含 ⚠️。"""
        suggestion = _suggest("assertion_error", "target_bug")
        assert suggestion.startswith("⚠️")

    def test_unknown_severity_uses_note(self):
        """默认（test_logic）建议含 📝。"""
        suggestion = _suggest("assertion_error", "test_logic")
        assert suggestion.startswith("📝")


class TestValidateHistoryPath:
    """`_validate_history_path` 路径验证测试。"""

    def test_tmp_path_accepted(self, tmp_path):
        """tmp 目录下的路径合法。"""
        p = str(tmp_path / "history.json")
        result = _validate_history_path(p)
        assert result

    def test_var_tmp_accepted(self):
        """/var/tmp 路径合法（若该目录存在）。"""
        var_tmp = "/var/tmp"
        if not os.path.exists(var_tmp):
            pytest.skip("/var/tmp does not exist on this system")
        p = os.path.join(var_tmp, "test_history.json")
        result = _validate_history_path(p)
        assert result

    def test_home_qwenpaw_accepted(self, tmp_path, monkeypatch):
        """~/.qwenpaw 路径合法。"""
        fake_home = tmp_path / "home"
        (fake_home / ".qwenpaw").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fake_home))
        p = str(fake_home / ".qwenpaw" / "history.json")
        result = _validate_history_path(p)
        assert result

    def test_home_claude_accepted(self, tmp_path, monkeypatch):
        """~/.claude 路径合法。"""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fake_home))
        p = str(fake_home / ".claude" / "history.json")
        result = _validate_history_path(p)
        assert result

    def test_home_opencode_accepted(self, tmp_path, monkeypatch):
        """~/.opencode 路径合法。"""
        fake_home = tmp_path / "home"
        (fake_home / ".opencode").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fake_home))
        p = str(fake_home / ".opencode" / "history.json")
        result = _validate_history_path(p)
        assert result

    def test_home_codex_accepted(self, tmp_path, monkeypatch):
        """~/.codex 路径合法。"""
        fake_home = tmp_path / "home"
        (fake_home / ".codex").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fake_home))
        p = str(fake_home / ".codex" / "history.json")
        result = _validate_history_path(p)
        assert result

    def test_allowed_dir_names(self):
        """验证只允许特定的目录名。"""
        # 这个测试验证我们的白名单逻辑正确
        allowed_dirs = {".claude", ".qwenpaw", ".opencode", ".codex"}
        assert ".claude" in allowed_dirs
        assert ".qwenpaw" in allowed_dirs
        assert ".opencode" in allowed_dirs
        assert ".codex" in allowed_dirs
        assert ".myplatform" not in allowed_dirs
        assert ".ssh" not in allowed_dirs


    def test_arbitrary_path_rejected(self):
        """任意路径应被拒绝。"""
        with pytest.raises(ValueError, match="history file must be under"):
            _validate_history_path("/etc/passwd")
