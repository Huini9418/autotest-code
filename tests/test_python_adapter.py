# -*- coding: utf-8 -*-
"""Python 适配器测试 — 覆盖 Codex 审查修复点 C1/C2/M3/M5/M6/M7。

测试 AST 分析逻辑：函数签名提取、分支计数、复杂度、import 格式化。
"""
import ast
import os
import tempfile
from textwrap import dedent

import pytest

from lang import get_analyzer


@pytest.fixture
def analyzer():
    return get_analyzer("python")


# ---------------------------------------------------------------------------
# C1: kwonlyargs 不再缺失
# ---------------------------------------------------------------------------


class TestKwonlyArgs:
    """验证 keyword-only 参数被正确提取。"""

    def test_simple_kwonly(self, analyzer):
        code = "def f(a, *, b): pass"
        args = analyzer._extract_args(ast.parse(code).body[0])
        names = {a["name"]: a for a in args}
        assert "b" in names
        assert names["b"]["kind"] == "kwonly"
        assert names["b"]["has_default"] is False

    def test_kwonly_with_default(self, analyzer):
        code = "def f(a, *, b=10): pass"
        args = analyzer._extract_args(ast.parse(code).body[0])
        names = {a["name"]: a for a in args}
        assert names["b"]["kind"] == "kwonly"
        assert names["b"]["has_default"] is True
        assert names["b"]["default"] == "10"

    def test_kwonly_after_vararg(self, analyzer):
        code = "def f(*args, x, y=1): pass"
        args = analyzer._extract_args(ast.parse(code).body[0])
        names = {a["name"]: a for a in args}
        assert names["x"]["kind"] == "kwonly"
        assert names["x"]["has_default"] is False
        assert names["y"]["kind"] == "kwonly"
        assert names["y"]["has_default"] is True
        assert names["y"]["default"] == "1"

    def test_kwonly_with_kwarg(self, analyzer):
        code = "def f(*, a, b=1, **kw): pass"
        args = analyzer._extract_args(ast.parse(code).body[0])
        names = {a["name"]: a for a in args}
        assert names["a"]["kind"] == "kwonly"
        assert names["b"]["kind"] == "kwonly"
        assert names["kw"]["kind"] == "kwarg"

    def test_kwonly_annotation_preserved(self, analyzer):
        code = "def f(*, x: int, y: str = 'hi'): pass"
        args = analyzer._extract_args(ast.parse(code).body[0])
        names = {a["name"]: a for a in args}
        assert names["x"]["annotation"] == "int"
        assert names["y"]["annotation"] == "str"

    def test_mixed_args_kwonly_vararg_kwarg(self, analyzer):
        code = "def f(a, b=1, *args, c, d=2, **kw): pass"
        args = analyzer._extract_args(ast.parse(code).body[0])
        names = {a["name"]: a for a in args}
        assert names["a"]["kind"] if "kind" in names["a"] else True  # pos
        assert names["b"]["has_default"] is True
        assert names["args"]["kind"] == "vararg"
        assert names["c"]["kind"] == "kwonly"
        assert names["c"]["has_default"] is False
        assert names["d"]["kind"] == "kwonly"
        assert names["d"]["has_default"] is True
        assert names["kw"]["kind"] == "kwarg"

    def test_kwonly_false_default(self, analyzer):
        """kwonlyarg 默认值为 False/0/空字符串时应正确识别 has_default。"""
        code = "def f(*, x=False, y=0, z=''): pass"
        args = analyzer._extract_args(ast.parse(code).body[0])
        names = {a["name"]: a for a in args}
        assert names["x"]["has_default"] is True
        assert names["x"]["default"] == "False"
        assert names["y"]["has_default"] is True
        assert names["y"]["default"] == "0"
        assert names["z"]["has_default"] is True
        assert names["z"]["default"] == "''"


# ---------------------------------------------------------------------------
# C2: 嵌套函数分支不下钻
# ---------------------------------------------------------------------------


class TestNestedFunctionBranches:
    """验证嵌套函数/类的分支不计入外层函数。"""

    def test_nested_function_not_counted(self, analyzer):
        code = dedent("""
            def outer():
                if True:
                    def inner():
                        if True:
                            for i in range(10):
                                pass
                return 1
        """).strip()
        func = ast.parse(code).body[0]
        # outer 只有 1 个 if，inner 的 if+for 不计入
        assert analyzer._count_branches(func) == 1

    def test_nested_class_not_counted(self, analyzer):
        code = dedent("""
            def outer():
                if True:
                    class Inner:
                        def method(self):
                            if True: pass
                            while x: pass
                return 1
        """).strip()
        func = ast.parse(code).body[0]
        # outer 只有 1 个 if，Inner.method 的 if+while 不计入
        assert analyzer._count_branches(func) == 1

    def test_normal_function_branches_correct(self, analyzer):
        code = dedent("""
            def normal(a, b):
                if a > 0:
                    for i in range(10):
                        if b:
                            return i
                elif a < 0:
                    while b:
                        b -= 1
                return 0
        """).strip()
        func = ast.parse(code).body[0]
        # if + elif + for + if + while = 5
        assert analyzer._count_branches(func) == 5
        assert analyzer._cyclomatic_complexity(func) == 6

    def test_deeply_nested_not_counted(self, analyzer):
        code = dedent("""
            def outer():
                if a:
                    if b:
                        def middle():
                            if c:
                                def inner():
                                    while True: pass
        """).strip()
        func = ast.parse(code).body[0]
        # outer: if a + if b = 2（middle 和 inner 不计入）
        assert analyzer._count_branches(func) == 2


# ---------------------------------------------------------------------------
# M5: 相对 import 格式化
# ---------------------------------------------------------------------------


class TestRelativeImport:
    """验证相对 import 的点号不被丢失。"""

    def test_single_dot_import(self, analyzer):
        code = "from . import foo"
        node = ast.parse(code).body[0]
        assert analyzer._format_import(node) == "from . import foo"

    def test_double_dot_import(self, analyzer):
        code = "from .. import foo"
        node = ast.parse(code).body[0]
        assert analyzer._format_import(node) == "from .. import foo"

    def test_dot_module_import(self, analyzer):
        code = "from .sub import bar"
        node = ast.parse(code).body[0]
        assert analyzer._format_import(node) == "from .sub import bar"

    def test_double_dot_module_import(self, analyzer):
        code = "from ..sub.mod import bar"
        node = ast.parse(code).body[0]
        assert analyzer._format_import(node) == "from ..sub.mod import bar"

    def test_absolute_import_unchanged(self, analyzer):
        code = "from os.path import join"
        node = ast.parse(code).body[0]
        assert analyzer._format_import(node) == "from os.path import join"

    def test_plain_import_unchanged(self, analyzer):
        code = "import os"
        node = ast.parse(code).body[0]
        assert analyzer._format_import(node) == "import os"


# ---------------------------------------------------------------------------
# M6: IfExp + Match 分支计数
# ---------------------------------------------------------------------------


class TestIfExpAndMatch:
    """验证三元表达式和 match 语句被计入分支。"""

    def test_ifexp_counted(self, analyzer):
        code = "def f(x):\n    y = 1 if x > 0 else 0\n    return y"
        func = ast.parse(code).body[0]
        assert analyzer._count_branches(func) == 1

    def test_multiple_ifexp(self, analyzer):
        code = dedent("""
            def f(x):
                a = 1 if x > 0 else 0
                b = 2 if x < 10 else 3
                return a + b
        """).strip()
        func = ast.parse(code).body[0]
        assert analyzer._count_branches(func) == 2

    def test_match_counted(self, analyzer):
        code = dedent("""
            def f(x):
                match x:
                    case 1:
                        return 'one'
                    case 2:
                        return 'two'
                    case _:
                        return 'other'
        """).strip()
        func = ast.parse(code).body[0]
        # 3 match cases
        assert analyzer._count_branches(func) == 3

    def test_match_with_if_combined(self, analyzer):
        code = dedent("""
            def f(x):
                if x > 0:
                    match x:
                        case 1: return 1
                        case 2: return 2
                return 0
        """).strip()
        func = ast.parse(code).body[0]
        # 1 If + 2 Match cases = 3
        assert analyzer._count_branches(func) == 3


# ---------------------------------------------------------------------------
# M7: BoolOp 按 operands-1 计数
# ---------------------------------------------------------------------------


class TestBoolOpCounting:
    """验证 BoolOp 按 operands-1 计数（标准 McCabe 复杂度）。"""

    def test_two_operand_and(self, analyzer):
        code = "def f():\n    if a and b: return 1"
        func = ast.parse(code).body[0]
        # 1 If + 1 BoolOp (2 values → 1)
        assert analyzer._count_branches(func) == 2

    def test_three_operand_and(self, analyzer):
        code = "def f():\n    if a and b and c: return 1"
        func = ast.parse(code).body[0]
        # 1 If + 2 BoolOp (3 values → 2)
        assert analyzer._count_branches(func) == 3

    def test_two_operand_or(self, analyzer):
        code = "def f():\n    if a or b: return 1"
        func = ast.parse(code).body[0]
        # 1 If + 1 BoolOp (2 values → 1)
        assert analyzer._count_branches(func) == 2

    def test_mixed_and_or(self, analyzer):
        code = "def f():\n    if a and b or c: return 1"
        func = ast.parse(code).body[0]
        # 1 If + 2 BoolOp (outer or: 2 values → 1, inner and: 2 values → 1)
        assert analyzer._count_branches(func) == 3

    def test_multiple_boolops(self, analyzer):
        code = dedent("""
            def f():
                if a and b:
                    return 1
                if c or d or e:
                    return 2
        """).strip()
        func = ast.parse(code).body[0]
        # 2 If + 1 (a and b) + 2 (c or d or e) = 5
        assert analyzer._count_branches(func) == 5


# ---------------------------------------------------------------------------
# M3: venv / node_modules 目录排除
# ---------------------------------------------------------------------------


class TestCollectFilesExclusion:
    """验证虚拟环境和 node_modules 目录被排除。"""

    def test_skips_venv_directory(self, analyzer, tmp_path):
        # 创建 venv 目录含 .py 文件
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        (venv_dir / "site.py").write_text("x = 1")
        # 创建正常 .py 文件
        (tmp_path / "main.py").write_text("x = 1")
        result = analyzer._collect_files(str(tmp_path))
        assert any("main.py" in f for f in result)
        # 用 startswith 检查 venv 目录下的文件是否被排除
        venv_prefix = str(venv_dir)
        assert not any(f.startswith(venv_prefix) for f in result)

    def test_skips_dot_venv_directory(self, analyzer, tmp_path):
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        (venv_dir / "lib.py").write_text("x = 1")
        (tmp_path / "app.py").write_text("x = 1")
        result = analyzer._collect_files(str(tmp_path))
        assert any("app.py" in f for f in result)
        venv_prefix = str(venv_dir)
        assert not any(f.startswith(venv_prefix) for f in result)

    def test_skips_node_modules(self, analyzer, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "index.js").write_text("x = 1")
        (tmp_path / "main.py").write_text("x = 1")
        result = analyzer._collect_files(str(tmp_path))
        nm_prefix = str(nm)
        assert not any(f.startswith(nm_prefix) for f in result)

    def test_skips_pycache(self, analyzer, tmp_path):
        pc = tmp_path / "__pycache__"
        pc.mkdir()
        (pc / "mod.cpython-312.pyc").write_text("")
        (tmp_path / "mod.py").write_text("x = 1")
        result = analyzer._collect_files(str(tmp_path))
        assert not any("__pycache__" in f for f in result)

    def test_single_file_input(self, analyzer, tmp_path):
        f = tmp_path / "single.py"
        f.write_text("x = 1")
        result = analyzer._collect_files(str(f))
        assert result == [str(f)]

    def test_non_py_file_returns_empty(self, analyzer, tmp_path):
        f = tmp_path / "readme.txt"
        f.write_text("hello")
        result = analyzer._collect_files(str(f))
        assert result == []


# ---------------------------------------------------------------------------
# 完整 analyze 集成测试
# ---------------------------------------------------------------------------


class TestAnalyzeIntegration:
    """验证 analyze 完整流程。"""

    def test_analyze_function_with_kwonlyargs(self, analyzer, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text(dedent("""
            from . import utils

            def divide(a: int, b: int = 1, *, strict: bool = False) -> float:
                if b == 0:
                    raise ValueError("division by zero")
                if strict and a < 0:
                    raise ValueError("negative in strict mode")
                return a / b
        """).strip())
        result = analyzer.analyze(str(f))
        assert result["summary"]["total_files"] == 1
        assert result["summary"]["error_files"] == 0
        func = result["files"][0]["functions"][0]
        assert func["name"] == "divide"
        args = {a["name"]: a for a in func["args"]}
        assert args["strict"]["kind"] == "kwonly"
        assert args["strict"]["has_default"] is True
        # 2 If + 1 BoolOp (strict and a < 0) = 3
        assert func["branches"] == 3
        assert func["complexity"] == 4
        # 相对 import 格式正确
        assert "from . import utils" in result["files"][0]["imports"]

    def test_analyze_class_with_methods(self, analyzer, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text(dedent("""
            class Calculator:
                def add(self, x: int, y: int) -> int:
                    return x + y

                def safe_div(self, x, y, *, check=False):
                    def inner():
                        if check:
                            return y != 0
                        return True
                    if not inner():
                        raise ValueError
                    return x / y
        """).strip())
        result = analyzer.analyze(str(f))
        cls = result["files"][0]["classes"][0]
        assert cls["name"] == "Calculator"
        assert len(cls["methods"]) == 2
        safe_div = cls["methods"][1]
        # safe_div: 1 if (not inner()) — inner 的 if 不计入
        assert safe_div["branches"] == 1
        # kwonly check
        args = {a["name"]: a for a in safe_div["args"]}
        assert args["check"]["kind"] == "kwonly"

    def test_analyze_syntax_error_file(self, analyzer, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text("def f(:\n    pass")
        result = analyzer.analyze(str(f))
        assert result["summary"]["error_files"] == 1
        assert "error" in result["files"][0]

    def test_analyze_empty_file(self, analyzer, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        result = analyzer.analyze(str(f))
        assert result["summary"]["total_files"] == 0
