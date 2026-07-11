# -*- coding: utf-8 -*-
"""针对代码审查发现的 bug 的回归测试。

覆盖以下修复：
- Critical 1: 布尔正则误匹配 (len(x) > 0 里的 x)
- Critical 2: early return 未传播 negation guard
- Critical 3: !var / not var 语义反转
- High 4: obj.x 里的 x 被误绑到参数
- High 5: not (...) 语法污染跨语言 expected
"""
import textwrap

import pytest

from lang import get_analyzer
from lang.case_design import (
    _guess_boundary_from_comparison,
    _extract_condition_variables,
    _is_bare_boolean,
    _is_boolean_negated,
    _prettify_guard,
    _replace_not_wrapper,
)


# ---------------------------------------------------------------------------
# Critical 1: 布尔正则误匹配 —— len(x) / 函数调用参数
# ---------------------------------------------------------------------------


class TestBooleanRegexMisMatch:
    """`x` 出现在函数调用括号内不应被识别为布尔条件。"""

    def test_len_x_gt_0_not_boolean_for_x(self):
        """`len(x) > 0` 里的 x 是 list/str，不是布尔。"""
        result = _guess_boundary_from_comparison("len(x) > 0", "x")
        assert result is None

    def test_check_is_valid_call_not_boolean(self):
        """`isValid(x)` 里的 x 不是布尔。"""
        result = _guess_boundary_from_comparison("isValid(x)", "x")
        assert result is None

    def test_x_dot_length_gt_0_not_boolean(self):
        """`x.length > 0` 里的 x 不是纯布尔。"""
        result = _guess_boundary_from_comparison("x.length > 0", "x")
        assert result is None

    def test_x_as_bare_boolean_still_matched(self):
        """真正独立的布尔变量应该被识别。"""
        result = _guess_boundary_from_comparison("isPass", "isPass")
        assert result == ("__LANG_TRUE__", "__LANG_FALSE__")

    def test_bool_in_compound_and(self):
        """`a && isPass` 里的 isPass 应识别为布尔。"""
        result = _guess_boundary_from_comparison("a && isPass", "isPass")
        assert result == ("__LANG_TRUE__", "__LANG_FALSE__")


# ---------------------------------------------------------------------------
# Critical 3: !var / not var 语义反转
# ---------------------------------------------------------------------------


class TestBooleanNegation:
    """`!var` / `not var` 的 true/false 应该被交换。"""

    def test_bang_var_swaps(self):
        """`!isValid` 语义：让条件为真需要 isValid=false。"""
        result = _guess_boundary_from_comparison("!isValid", "isValid")
        assert result == ("__LANG_FALSE__", "__LANG_TRUE__")

    def test_not_var_swaps(self):
        """`not enabled` 语义：让条件为真需要 enabled=false。"""
        result = _guess_boundary_from_comparison("not enabled", "enabled")
        assert result == ("__LANG_FALSE__", "__LANG_TRUE__")

    def test_no_negation_stays(self):
        """无取反时 true/false 顺序保持不变。"""
        result = _guess_boundary_from_comparison("isValid", "isValid")
        assert result == ("__LANG_TRUE__", "__LANG_FALSE__")

    def test_is_boolean_negated_bang(self):
        assert _is_boolean_negated("!isValid", "isValid") is True

    def test_is_boolean_negated_not_keyword(self):
        assert _is_boolean_negated("not enabled", "enabled") is True

    def test_is_boolean_not_negated(self):
        assert _is_boolean_negated("isValid", "isValid") is False

    def test_bang_var_in_compound(self):
        """`a && !isValid` 里 isValid 也应被视为取反。"""
        assert _is_boolean_negated("a && !isValid", "isValid") is True


# ---------------------------------------------------------------------------
# High 4: 成员访问 `obj.x` 里的 x 不应绑到参数
# ---------------------------------------------------------------------------


class TestMemberAccessNoBinding:
    """`obj.x` 中的 `x` 不应被识别为参数 `x` 的比较。"""

    def test_obj_x_gt_5_not_match_x(self):
        result = _guess_boundary_from_comparison("obj.x > 5", "x")
        assert result is None

    def test_x_dot_attr_not_match_x(self):
        result = _guess_boundary_from_comparison("x.attr > 5", "x")
        assert result is None

    def test_bare_x_still_matches(self):
        """真正比较 x 时仍能匹配。"""
        result = _guess_boundary_from_comparison("x > 5", "x")
        assert result == ("6", "5")

    def test_variables_extract_skips_property(self):
        """`obj.x > 5` 只提出 obj，不提 x。"""
        vars = _extract_condition_variables("obj.x > 5")
        assert "obj" in vars
        assert "x" not in vars

    def test_variables_extract_skips_function_name(self):
        """`len(x) > 0` 只提出 x，不提 len。"""
        vars = _extract_condition_variables("len(x) > 0")
        assert "x" in vars
        assert "len" not in vars

    def test_variables_extract_skips_namespace_prefix(self):
        """`A::B::foo(x)` 只提 A 和 x。"""
        vars = _extract_condition_variables("A::B::foo(x)")
        assert "A" in vars
        assert "B" not in vars  # B 前面是 ::
        assert "x" in vars
        assert "foo" not in vars  # foo 后面是 (


# ---------------------------------------------------------------------------
# High 5: 跨语言 negation 语法污染
# ---------------------------------------------------------------------------


class TestPrettifyGuard:
    """内部 guard 转成面向用户的可读描述，不泄漏 Python 语法。"""

    def test_prettify_negation(self):
        """`not (X)` 应变成 `非 (X)`。"""
        result = _prettify_guard("not (x < 0)")
        assert result == "非 (x < 0)"

    def test_prettify_and(self):
        """`A and B` 顶层 and 应变成中文 `A 且 B`。"""
        result = _prettify_guard("x > 0 and y < 5")
        assert result == "x > 0 且 y < 5"

    def test_prettify_combined(self):
        """`not (X) and Y` 应变成 `非 (X) 且 Y`。"""
        result = _prettify_guard("not (x < 0) and y == 1")
        assert result == "非 (x < 0) 且 y == 1"

    def test_prettify_empty(self):
        assert _prettify_guard("") == ""

    def test_prettify_no_change(self):
        """普通条件不被改动。"""
        result = _prettify_guard("x > 0")
        assert result == "x > 0"

    def test_replace_not_wrapper_nested(self):
        """嵌套 `not (not (X))` 只替换外层第一层。"""
        # 外层 not( 后是 not (，所以外层匹配到 `not (not (X))`
        # 结果为 `非 (not (X))`
        result = _replace_not_wrapper("not (not (X))")
        assert "非 (" in result

    def test_replace_not_wrapper_does_not_touch_cannot(self):
        """`cannot` 里的 not 不应被识别（前面是字母）。"""
        result = _replace_not_wrapper("cannot foo")
        assert result == "cannot foo"


# ---------------------------------------------------------------------------
# Critical 2: Early return 未传播 negation guard
# ---------------------------------------------------------------------------


class TestEarlyReturnGuardPropagation:
    """`if bad: return; return good` 里的 return good 应带 not (bad) guard。"""

    def _get_returns(self, code: str) -> list[dict]:
        """辅助方法：分析代码返回第一个函数的 returns_info。"""
        analyzer = get_analyzer("python")
        import tempfile, os
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False
        ) as f:
            f.write(textwrap.dedent(code))
            path = f.name
        try:
            result = analyzer.analyze(path)
            fn = result["files"][0]["functions"][0]
            return fn["returns_info"]
        finally:
            os.unlink(path)

    def test_single_early_return(self):
        """简单的 early return + fall-through。"""
        rets = self._get_returns("""
            def classify(x):
                if x < 0:
                    return "neg"
                return "pos"
        """)
        assert len(rets) == 2
        neg_ret = next(r for r in rets if r["value"] == "'neg'")
        pos_ret = next(r for r in rets if r["value"] == "'pos'")
        assert neg_ret["guard"] == "x < 0"
        # 关键断言：pos 的 guard 应有 not (x < 0)
        assert "not (x < 0)" in pos_ret["guard"]

    def test_multi_early_return_accumulates(self):
        """连续多个 early return 应累积 negation。"""
        rets = self._get_returns("""
            def multi(x, y):
                if x < 0:
                    return "a"
                if y == 0:
                    return "b"
                return "c"
        """)
        c_ret = next(r for r in rets if r["value"] == "'c'")
        # c 的 guard 应包含 not (x < 0) 和 not (y == 0)
        assert "not (x < 0)" in c_ret["guard"]
        assert "not (y == 0)" in c_ret["guard"]

    def test_raise_terminates_too(self):
        """early raise 也算 terminates，也传播 negation。"""
        rets = self._get_returns("""
            def divide(a, b):
                if b == 0:
                    raise ValueError("zero")
                return a / b
        """)
        ret = next(r for r in rets if r["kind"] == "return")
        assert "not (b == 0)" in ret["guard"]

    def test_if_with_else_no_implicit_negation(self):
        """有 else 分支的 if，不应导致 implicit negation
        （因为不是 early return 模式，else 已经处理了）。
        """
        rets = self._get_returns("""
            def classify(x):
                if x < 0:
                    y = 1
                else:
                    y = 2
                return y
        """)
        ret = next(r for r in rets if r["kind"] == "return")
        # 这里 return y 是无条件的（if/else 都不 terminate）
        assert ret["guard"] == ""


# ---------------------------------------------------------------------------
# 集成测试：整个 case_design 流程
# ---------------------------------------------------------------------------


class TestDecisionTableExpectedText:
    """检查决策表用例的 expected 文本，验证跨语言不会泄漏 Python 语法。"""

    def test_js_decision_table_no_python_not(self):
        """JS 的决策表 expected 不应包含 Python 的 `not (...)`。"""
        analyzer = get_analyzer("javascript")
        import tempfile, os
        code = """
        function f(x, y) {
            if (x > 0 && y < 5) return 'A';
            return 'B';
        }
        """
        with tempfile.NamedTemporaryFile(
            suffix=".js", mode="w", delete=False
        ) as f:
            f.write(code)
            path = f.name
        try:
            analysis = analyzer.analyze(path)
            cases = analyzer.gen_cases(analysis)
            decision_cases = [
                c for c in cases["test_cases"]
                if c["type"] == "decision_table"
            ]
            for c in decision_cases:
                expected = c["expected"]
                # 不允许 Python 语法泄漏（前后加空格避免误报 "cannot" 等）
                assert "not (" not in expected, (
                    f"Python not(...) leaked in JS expected: {expected}"
                )
                assert " and " not in expected, (
                    f"Python 'and' leaked in JS expected: {expected}"
                )
        finally:
            os.unlink(path)
