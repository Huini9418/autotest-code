# -*- coding: utf-8 -*-
"""用例设计共享算法测试。

验证四种用例类型：等价类/边界值/异常路径/决策表。
"""
import os
import json

import pytest

from lang import get_analyzer
from lang.case_design import design_cases, _resolve_type


# ---------------------------------------------------------------------------
# 四种用例类型
# ---------------------------------------------------------------------------


@pytest.fixture
def analyzer():
    return get_analyzer("python")


@pytest.fixture
def analysis_with_branches(analyzer, tmp_path):
    """有分支的函数分析结果。"""
    f = tmp_path / "sample.py"
    f.write_text(
        "def divide(a: int, b: int = 1) -> float:\n"
        "    if b == 0:\n"
        "        raise ValueError()\n"
        "    return a / b\n"
    )
    return analyzer.analyze(str(f))


@pytest.fixture
def analysis_simple(analyzer, tmp_path):
    """无分支的简单函数。"""
    f = tmp_path / "sample.py"
    f.write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
    return analyzer.analyze(str(f))


class TestCaseTypes:
    """验证四种用例类型正确生成。"""

    def test_equivalence_class_generated(self, analysis_simple):
        from lang.python_lang import TYPE_BOUNDARIES, TYPE_NORMALS

        result = design_cases(analysis_simple, TYPE_BOUNDARIES, TYPE_NORMALS)
        types = {tc["type"] for tc in result["test_cases"]}
        assert "equivalence_class" in types

    def test_boundary_value_generated_for_typed_args(self, analysis_simple):
        from lang.python_lang import TYPE_BOUNDARIES, TYPE_NORMALS

        result = design_cases(analysis_simple, TYPE_BOUNDARIES, TYPE_NORMALS)
        types = {tc["type"] for tc in result["test_cases"]}
        assert "boundary_value" in types

    def test_exception_path_generated_when_branches(self, analysis_with_branches):
        from lang.python_lang import TYPE_BOUNDARIES, TYPE_NORMALS

        result = design_cases(analysis_with_branches, TYPE_BOUNDARIES, TYPE_NORMALS)
        types = {tc["type"] for tc in result["test_cases"]}
        assert "exception_path" in types

    def test_exception_path_not_generated_when_no_branches(self, analysis_simple):
        from lang.python_lang import TYPE_BOUNDARIES, TYPE_NORMALS

        result = design_cases(analysis_simple, TYPE_BOUNDARIES, TYPE_NORMALS)
        types = {tc["type"] for tc in result["test_cases"]}
        assert "exception_path" not in types

    def test_decision_table_generated_when_3_branches(self, analyzer, tmp_path):
        from lang.python_lang import TYPE_BOUNDARIES, TYPE_NORMALS

        f = tmp_path / "sample.py"
        # 3 个 if 分支：if + elif + nested if = 3
        f.write_text(
            "def f(x: int) -> int:\n"
            "    if x > 0:\n"
            "        if x > 10:\n"
            "            return 2\n"
            "        elif x > 5:\n"
            "            return 1\n"
            "    return 0\n"
        )
        analysis = analyzer.analyze(str(f))
        result = design_cases(analysis, TYPE_BOUNDARIES, TYPE_NORMALS)
        types = {tc["type"] for tc in result["test_cases"]}
        assert "decision_table" in types

    def test_summary_correct(self, analysis_simple):
        from lang.python_lang import TYPE_BOUNDARIES, TYPE_NORMALS

        result = design_cases(analysis_simple, TYPE_BOUNDARIES, TYPE_NORMALS)
        summary = result["summary"]
        assert summary["total_cases"] == len(result["test_cases"])
        total_by_type = sum(summary["by_type"].values())
        assert total_by_type == summary["total_cases"]


# ---------------------------------------------------------------------------
# _resolve_type 类型解析
# ---------------------------------------------------------------------------


class TestResolveType:
    """验证类型注解解析。"""

    def test_plain_type(self):
        assert _resolve_type("int", {"int": ["42"]}) == "int"

    def test_optional_type(self):
        normals = {"int": ["42"]}
        assert _resolve_type("Optional[int]", normals) == "int"

    def test_union_type(self):
        normals = {"int": ["42"], "str": ["hi"]}
        assert _resolve_type("Union[int, str]", normals) == "int"

    def test_union_with_none(self):
        normals = {"int": ["42"]}
        assert _resolve_type("Union[int, None]", normals) == "int"

    def test_empty_annotation(self):
        assert _resolve_type("", {}) == ""

    def test_unknown_type_returns_original(self):
        assert _resolve_type("CustomType", {}) == "CustomType"

    def test_optional_unknown_type(self):
        """Optional[Custom] 返回 Custom（与 PEP 604 Custom | None 一致）。"""
        assert _resolve_type("Optional[Custom]", {}) == "Custom"

    def test_union_unknown_type_returns_first(self):
        """Union[Custom, Other] 无已知类型时返回第一个。"""
        assert _resolve_type("Union[Custom, Other]", {}) == "Custom"

    # L1: PEP 604 X | Y 语法支持

    def test_pep604_union(self):
        normals = {"int": ["42"], "str": ["hi"]}
        assert _resolve_type("int | str", normals) == "int"

    def test_pep604_with_none(self):
        normals = {"int": ["42"]}
        assert _resolve_type("int | None", normals) == "int"

    def test_pep604_none_first(self):
        normals = {"int": ["42"]}
        assert _resolve_type("None | int", normals) == "int"

    def test_pep604_unknown_types_returns_first(self):
        assert _resolve_type("Custom | Other", {}) == "Custom"

    def test_pep604_three_types(self):
        normals = {"int": ["42"], "str": ["hi"]}
        assert _resolve_type("int | str | None", normals) == "int"

    def test_pep604_no_spaces(self):
        normals = {"int": ["42"]}
        assert _resolve_type("int|str", normals) == "int"

    def test_pep604_all_unknown_returns_first(self):
        """全是未知类型时返回第一个非 None 类型。"""
        assert _resolve_type("Foo | Bar", {}) == "Foo"

    def test_pep604_with_known_second(self):
        """第一个类型未知，第二个已知 → 返回已知的。"""
        normals = {"str": ["hi"]}
        assert _resolve_type("Custom | str", normals) == "str"


# ---------------------------------------------------------------------------
# gen_cases 通过 analyzer 入口
# ---------------------------------------------------------------------------


class TestGenCasesViaAnalyzer:
    """验证 analyzer.gen_cases 返回结构。"""

    def test_returns_test_cases_and_summary(self, analyzer, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("def f(a: int) -> int:\n    return a\n")
        analysis = analyzer.analyze(str(f))
        result = analyzer.gen_cases(analysis)
        assert "test_cases" in result
        assert "summary" in result
        assert isinstance(result["test_cases"], list)

    def test_each_case_has_required_fields(self, analyzer, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("def f(a: int) -> int:\n    if a > 0: return a\n    return 0\n")
        analysis = analyzer.analyze(str(f))
        result = analyzer.gen_cases(analysis)
        for tc in result["test_cases"]:
            assert "target" in tc
            assert "type" in tc
            assert "description" in tc
            assert "inputs" in tc
            assert "expected" in tc

    def test_error_files_skipped(self, analyzer, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text("def f(:\n    pass")
        analysis = analyzer.analyze(str(f))
        result = analyzer.gen_cases(analysis)
        assert len(result["test_cases"]) == 0


# ---------------------------------------------------------------------------
# L3: gen_cases.py --filter 大小写不敏感
# ---------------------------------------------------------------------------


class TestGenCasesFilter:
    """验证 gen_cases.py --filter 大小写不敏感匹配。"""

    def _run_gen_cases(self, analysis_file, filter_str, tmp_path):
        """运行 gen_cases.py 并返回 JSON 输出。"""
        import subprocess
        import sys

        output_file = str(tmp_path / "cases.json")
        test_dir = os.path.dirname(os.path.abspath(__file__))
        scripts_dir = os.path.normpath(os.path.join(
            test_dir,
            "..", "skills", "autotest-code-zh", "scripts"
        ))
        script = os.path.join(scripts_dir, "gen_cases.py")
        result = subprocess.run(
            [
                sys.executable,
                script,
                "--analysis-file",
                str(analysis_file),
                "--filter",
                filter_str,
                "--output",
                output_file,
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"gen_cases.py failed: {result.stderr}"
        with open(output_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_filter_case_insensitive_upper(self, analyzer, tmp_path):
        """大写 filter 应匹配小写函数名。"""
        f = tmp_path / "sample.py"
        f.write_text(
            "def processData(data: int) -> int:\n"
            "    if data > 0:\n"
            "        return data\n"
            "    return 0\n"
        )
        analysis = analyzer.analyze(str(f))
        analysis_file = tmp_path / "analysis.json"
        analysis_file.write_text(
            json.dumps(analysis, ensure_ascii=False)
        )
        result = self._run_gen_cases(analysis_file, "PROCESS", tmp_path)
        targets = {tc["target"] for tc in result["test_cases"]}
        assert "processData" in targets

    def test_filter_case_insensitive_mixed(self, analyzer, tmp_path):
        """混合大小写 filter 应匹配。"""
        f = tmp_path / "sample.py"
        f.write_text(
            "def processData(data: int) -> int:\n"
            "    return data\n"
        )
        analysis = analyzer.analyze(str(f))
        analysis_file = tmp_path / "analysis.json"
        analysis_file.write_text(
            json.dumps(analysis, ensure_ascii=False)
        )
        result = self._run_gen_cases(
            analysis_file, "PrOcEsS", tmp_path
        )
        targets = {tc["target"] for tc in result["test_cases"]}
        assert "processData" in targets

    def test_filter_no_match_returns_empty(self, analyzer, tmp_path):
        """不匹配的 filter 返回空用例列表。"""
        f = tmp_path / "sample.py"
        f.write_text("def foo(x: int) -> int:\n    return x\n")
        analysis = analyzer.analyze(str(f))
        analysis_file = tmp_path / "analysis.json"
        analysis_file.write_text(
            json.dumps(analysis, ensure_ascii=False)
        )
        result = self._run_gen_cases(analysis_file, "bar", tmp_path)
        assert len(result["test_cases"]) == 0
