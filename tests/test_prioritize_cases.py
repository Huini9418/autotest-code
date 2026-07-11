# -*- coding: utf-8 -*-
"""针对 prioritize_cases 和 severity 打标的测试。

覆盖:
- Severity 常量表和 _weight_to_severity 函数
- 各种用例类型是否正确打上 severity
- prioritize_cases 的排序、上限、保底
- design_cases 集成流程的 summary 变化
"""
import textwrap

import pytest

from lang import get_analyzer
from lang.case_design import (
    DEFAULT_SEVERITY,
    DEFAULT_QUOTAS,
    BOUNDARY_CATEGORY_WEIGHT,
    SECURITY_CATEGORY_WEIGHT,
    _weight_to_severity,
    _score_case,
    prioritize_cases,
    _count_by_severity,
)


# ---------------------------------------------------------------------------
# _weight_to_severity
# ---------------------------------------------------------------------------


class TestWeightToSeverity:
    """权重到 severity 的映射。"""

    def test_high_weight_promotes_to_high(self):
        """>= 0.8 从 medium 升到 high。"""
        assert _weight_to_severity(0.9, base="medium") == "high"
        assert _weight_to_severity(1.0, base="medium") == "high"

    def test_low_weight_demotes_to_low(self):
        """< 0.4 从 medium 降到 low。"""
        assert _weight_to_severity(0.2, base="medium") == "low"
        assert _weight_to_severity(0.3, base="medium") == "low"

    def test_mid_weight_keeps_base(self):
        """0.4 - 0.79 保持 base。"""
        assert _weight_to_severity(0.5, base="medium") == "medium"
        assert _weight_to_severity(0.7, base="medium") == "medium"

    def test_critical_base_never_downgrades(self):
        """base=critical 不会被降级。"""
        assert _weight_to_severity(0.1, base="critical") == "critical"
        assert _weight_to_severity(0.9, base="critical") == "critical"


# ---------------------------------------------------------------------------
# Severity 打标：各种 case 类型
# ---------------------------------------------------------------------------


class TestSeverityLabeling:
    """检查各类 case 生成时是否正确打上 severity。"""

    @pytest.fixture
    def analyzer(self):
        return get_analyzer("python")

    def _analyze_and_gen(self, analyzer, tmp_path, code):
        f = tmp_path / "sample.py"
        f.write_text(textwrap.dedent(code))
        analysis = analyzer.analyze(str(f))
        return analyzer.gen_cases(analysis)

    def test_all_cases_have_severity(self, analyzer, tmp_path):
        """所有用例都应有 severity 字段。"""
        code = """
            def divide(a: int, b: int) -> float:
                if b == 0:
                    raise ValueError("zero")
                return a / b
        """
        result = self._analyze_and_gen(analyzer, tmp_path, code)
        for c in result["test_cases"]:
            assert "severity" in c, f"缺 severity: {c}"
            assert c["severity"] in ("critical", "high", "medium", "low")

    def test_decision_table_is_critical(self, analyzer, tmp_path):
        """decision_table 应是 critical。"""
        code = """
            def check(u: int, s: int, p: bool) -> str:
                if u == 2 and s >= 100 and p:
                    return "vip"
                elif u == 1:
                    return "normal"
                return "guest"
        """
        result = self._analyze_and_gen(analyzer, tmp_path, code)
        dt_cases = [c for c in result["test_cases"] if c["type"] == "decision_table"]
        assert len(dt_cases) > 0
        for c in dt_cases:
            assert c["severity"] == "critical"

    def test_boundary_zero_is_high(self, analyzer, tmp_path):
        """boundary_value 里 category=zero 应升为 high。"""
        code = """
            def f(x: int) -> int:
                return x + 1
        """
        result = self._analyze_and_gen(analyzer, tmp_path, code)
        # 找出 category=zero 的 boundary 用例
        zeros = [
            c for c in result["test_cases"]
            if c["type"] == "boundary_value" and "(zero)" in c["description"]
        ]
        # 至少要有一个 zero 边界值用例（如果被筛掉说明没保留）
        # 用无 quota 版本再验证
        if not zeros:
            # 直接检查所有生成的 case（不 prioritize）
            from lang.python_lang import PythonAnalyzer, TYPE_BOUNDARIES, TYPE_NORMALS
            from lang.case_design import _gen_for_function
            analysis = analyzer.analyze(str(tmp_path / "sample.py"))
            for fdata in analysis["files"]:
                for fn in fdata.get("functions", []):
                    raw = _gen_for_function(
                        fdata["file"], fn, TYPE_BOUNDARIES, TYPE_NORMALS
                    )
                    zeros.extend([
                        c for c in raw
                        if c["type"] == "boundary_value"
                        and "(zero)" in c["description"]
                    ])
        assert zeros, "应至少有一个 zero 边界用例"
        for c in zeros:
            assert c["severity"] == "high", (
                f"zero 边界应 high, got {c['severity']}"
            )

    def test_boundary_large_is_low(self, analyzer, tmp_path):
        """boundary_value 里 category=large 应降为 low（权重 0.3）。"""
        code = """
            def f(x: int) -> int:
                return x + 1
        """
        # 需要检查 raw cases 因为 large 可能被 quota 筛掉
        from lang.python_lang import TYPE_BOUNDARIES, TYPE_NORMALS
        from lang.case_design import _gen_for_function
        f = tmp_path / "sample.py"
        f.write_text(textwrap.dedent(code))
        analysis = analyzer.analyze(str(f))
        for fdata in analysis["files"]:
            for fn in fdata.get("functions", []):
                raw = _gen_for_function(
                    fdata["file"], fn, TYPE_BOUNDARIES, TYPE_NORMALS
                )
                larges = [
                    c for c in raw
                    if c["type"] == "boundary_value"
                    and "(large)" in c["description"]
                ]
                assert larges
                for c in larges:
                    assert c["severity"] == "low"

    def test_security_test_is_high(self, analyzer, tmp_path):
        """security_test（sql_injection/xss 等）应是 high。"""
        code = """
            def query(user_input: str) -> str:
                return f"SELECT * WHERE name = {user_input}"
        """
        # 检查 raw cases
        from lang.python_lang import TYPE_BOUNDARIES, TYPE_NORMALS
        from lang.case_design import _gen_for_function
        f = tmp_path / "sample.py"
        f.write_text(textwrap.dedent(code))
        analysis = analyzer.analyze(str(f))
        for fdata in analysis["files"]:
            for fn in fdata.get("functions", []):
                raw = _gen_for_function(
                    fdata["file"], fn, TYPE_BOUNDARIES, TYPE_NORMALS
                )
                sec = [c for c in raw if c["type"] == "security_test"]
                assert sec, "应有 security_test 用例"
                for c in sec:
                    assert c["severity"] == "high"

    def test_equivalence_class_is_low(self, analyzer, tmp_path):
        """equivalence_class 应是 low。"""
        code = """
            def f(x: int) -> int:
                return x + 1
        """
        result = self._analyze_and_gen(analyzer, tmp_path, code)
        eq = [c for c in result["test_cases"] if c["type"] == "equivalence_class"]
        assert eq
        for c in eq:
            assert c["severity"] == "low"


# ---------------------------------------------------------------------------
# prioritize_cases
# ---------------------------------------------------------------------------


class TestPrioritizeCases:
    """prioritize_cases 排序 + 硬上限逻辑。"""

    def test_empty_returns_empty(self):
        assert prioritize_cases([]) == []

    def test_respects_total_max(self):
        """超过 total_max 的用例被裁掉。"""
        cases = [
            {"target": "f", "type": "boundary_value", "severity": "medium"}
            for _ in range(50)
        ]
        result = prioritize_cases(cases, {"total_max": 5, "per_type_max": {}, "min_by_severity": {}})
        assert len(result) == 5

    def test_critical_sorted_first(self):
        """critical 用例排在前面。"""
        cases = [
            {"target": "f", "type": "boundary_value", "severity": "low"},
            {"target": "f", "type": "decision_table", "severity": "critical"},
            {"target": "f", "type": "boundary_value", "severity": "medium"},
        ]
        result = prioritize_cases(cases)
        assert result[0]["severity"] == "critical"

    def test_per_type_max_enforced(self):
        """per_type_max 限制某类型的数量。"""
        cases = [
            {"target": "f", "type": "boundary_value", "severity": "high"}
            for _ in range(20)
        ]
        quotas = {
            "total_max": 15,
            "per_type_max": {"boundary_value": 3},
            "min_by_severity": {},
        }
        result = prioritize_cases(cases, quotas)
        assert len(result) == 3
        assert all(c["type"] == "boundary_value" for c in result)

    def test_min_by_severity_saves_critical(self):
        """min_by_severity 保证 critical 一定被保留。"""
        # 50 个 low + 1 个 critical
        cases = (
            [{"target": "f", "type": "boundary_value", "severity": "low"} for _ in range(50)]
            + [{"target": "f", "type": "decision_table", "severity": "critical"}]
        )
        quotas = {
            "total_max": 3,
            "per_type_max": {"boundary_value": 10, "decision_table": 5},
            "min_by_severity": {"critical": 1},
        }
        result = prioritize_cases(cases, quotas)
        # 3 个总用例，第一个必是 critical
        assert len(result) == 3
        assert any(c["severity"] == "critical" for c in result)

    def test_score_case_matches_severity(self):
        """_score_case 应正确按 severity 打分。"""
        assert _score_case({"severity": "critical"}) > _score_case({"severity": "high"})
        assert _score_case({"severity": "high"}) > _score_case({"severity": "medium"})
        assert _score_case({"severity": "medium"}) > _score_case({"severity": "low"})

    def test_stable_sort_by_type_when_same_severity(self):
        """同 severity 内按类型优先级稳定排序。"""
        cases = [
            {"target": "f", "type": "boundary_value", "severity": "high"},
            {"target": "f", "type": "exception_path", "severity": "high"},
        ]
        result = prioritize_cases(cases, {"total_max": 10, "per_type_max": {}, "min_by_severity": {}})
        # exception_path 优先级更高（type_priority=1 vs boundary_value=2）
        assert result[0]["type"] == "exception_path"


# ---------------------------------------------------------------------------
# 集成：design_cases 的 summary 变化
# ---------------------------------------------------------------------------


class TestDesignCasesSummary:
    """design_cases 返回的 summary 应含 severity 统计和筛选信息。"""

    @pytest.fixture
    def analyzer(self):
        return get_analyzer("python")

    def test_summary_has_severity_stats(self, analyzer, tmp_path):
        """summary 应包含 by_severity 字段。"""
        f = tmp_path / "sample.py"
        f.write_text(textwrap.dedent("""
            def divide(a: int, b: int) -> float:
                if b == 0:
                    raise ValueError("zero")
                return a / b
        """))
        result = analyzer.gen_cases(analyzer.analyze(str(f)))
        assert "by_severity" in result["summary"]
        assert "raw_total" in result["summary"]
        assert "filtered_out" in result["summary"]

    def test_complex_function_filtered(self, analyzer, tmp_path):
        """复杂函数应触发筛选，raw_total > total_cases。"""
        f = tmp_path / "sample.py"
        f.write_text(textwrap.dedent("""
            def process(a: int, b: str, c: bool, d: int) -> str:
                if a <= 0: raise ValueError("a")
                if not b: raise ValueError("b")
                if d <= 0: raise ValueError("d")
                if c and d > 100:
                    return "big"
                if c: return "vip"
                return "normal"
        """))
        result = analyzer.gen_cases(analyzer.analyze(str(f)))
        summary = result["summary"]
        # 有多参数 + 多分支，raw 用例数应远大于筛选后
        assert summary["raw_total"] > summary["total_cases"]
        assert summary["filtered_out"] > 0
        # 筛选后不超过 total_max（默认 15）
        assert summary["total_cases"] <= DEFAULT_QUOTAS["total_max"]

    def test_simple_function_not_filtered(self, analyzer, tmp_path):
        """简单函数经 prioritize 后不超过 total_max。"""
        f = tmp_path / "sample.py"
        f.write_text(textwrap.dedent("""
            def add(a: int, b: int) -> int:
                return a + b
        """))
        result = analyzer.gen_cases(analyzer.analyze(str(f)))
        summary = result["summary"]
        # 简单函数筛选后不超过 total_max
        assert summary["total_cases"] <= DEFAULT_QUOTAS["total_max"]
        # raw_total 应该 >= 筛选后的数量
        assert summary["raw_total"] >= summary["total_cases"]

    def test_critical_preserved_in_complex(self, analyzer, tmp_path):
        """复杂函数筛选后，critical 用例应被完全保留。"""
        f = tmp_path / "sample.py"
        f.write_text(textwrap.dedent("""
            def process(a: int, b: str, c: bool, d: int) -> str:
                if a <= 0: raise ValueError("a")
                if not b: raise ValueError("b")
                if c and d > 100:
                    return "big"
                if c: return "vip"
                return "normal"
        """))
        result = analyzer.gen_cases(analyzer.analyze(str(f)))
        critical_kept = [
            c for c in result["test_cases"] if c["severity"] == "critical"
        ]
        # 至少要有几个 critical 决策表用例被保留
        assert len(critical_kept) >= 3

    def test_summary_by_severity_counts_correct(self, analyzer, tmp_path):
        """summary.by_severity 的数字应与用例列表一致。"""
        f = tmp_path / "sample.py"
        f.write_text(textwrap.dedent("""
            def check(x: int) -> str:
                if x < 0: return "neg"
                if x == 0: return "zero"
                return "pos"
        """))
        result = analyzer.gen_cases(analyzer.analyze(str(f)))
        actual = _count_by_severity(result["test_cases"])
        assert actual == result["summary"]["by_severity"]


# ---------------------------------------------------------------------------
# 常量表基础检查
# ---------------------------------------------------------------------------


class TestConstants:
    """确保常量表的合理性。"""

    def test_default_severity_covers_all_types(self):
        """DEFAULT_SEVERITY 应覆盖所有 7 种用例类型。"""
        expected_types = {
            "decision_table", "exception_path", "security_test",
            "boundary_value", "edge_case", "equivalence_class",
            "performance",
        }
        assert set(DEFAULT_SEVERITY.keys()) >= expected_types

    def test_default_severity_values_valid(self):
        """DEFAULT_SEVERITY 的所有值应是合法 severity。"""
        for v in DEFAULT_SEVERITY.values():
            assert v in ("critical", "high", "medium", "low")

    def test_boundary_weight_sql_injection_high(self):
        """SQL 注入应是最高权重 1.0。"""
        assert SECURITY_CATEGORY_WEIGHT["sql_injection"] == 1.0

    def test_boundary_zero_high_weight(self):
        """zero 是最常见 bug 源，权重应 >= 0.9。"""
        assert BOUNDARY_CATEGORY_WEIGHT["zero"] >= 0.9

    def test_default_quotas_reasonable(self):
        """默认 quotas 的数字合理。"""
        assert DEFAULT_QUOTAS["total_max"] > 0
        assert DEFAULT_QUOTAS["total_max"] <= 50  # 不至于失控大
        assert sum(DEFAULT_QUOTAS["per_type_max"].values()) >= (
            DEFAULT_QUOTAS["total_max"]
        )  # 各类型上限总和 >= 总上限，否则达不到 total_max
