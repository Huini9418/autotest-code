# -*- coding: utf-8 -*-
"""JavaScript 适配器测试 — Phase 2 验证 tree-sitter 多语言架构。

测试 JS AST 分析：函数提取、类/方法、箭头函数、分支计数、import。
"""
import os
import tempfile

import pytest

from lang import get_analyzer


@pytest.fixture
def analyzer():
    return get_analyzer("javascript")


def _write_js(tmp_path, code, name="sample.js"):
    """写 JS 文件并返回路径。"""
    f = tmp_path / name
    f.write_text(code)
    return str(f)


# ---------------------------------------------------------------------------
# 函数提取
# ---------------------------------------------------------------------------


class TestFunctionExtraction:
    """验证函数声明和箭头函数提取。"""

    def test_function_declaration(self, analyzer, tmp_path):
        f = _write_js(tmp_path, "function add(a, b) { return a + b; }")
        result = analyzer.analyze(f)
        assert result["summary"]["total_functions"] == 1
        func = result["files"][0]["functions"][0]
        assert func["name"] == "add"
        assert len(func["args"]) == 2
        assert func["is_async"] is False

    def test_arrow_function(self, analyzer, tmp_path):
        f = _write_js(tmp_path, "const add = (a, b) => a + b;")
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["name"] == "add"
        assert len(func["args"]) == 2

    def test_function_expression(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path, "const mul = function(a, b) { return a * b; };"
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["name"] == "mul"

    def test_async_function(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "async function fetchData(url) { return fetch(url); }",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["name"] == "fetchData"
        assert func["is_async"] is True

    def test_async_arrow_function(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path, "const fn = async (x) => x;"
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["is_async"] is True

    def test_function_with_default_param(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path, "function f(a, b = 10) { return a + b; }"
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        args = {a["name"]: a for a in func["args"]}
        assert args["a"]["has_default"] is False
        assert args["b"]["has_default"] is True
        assert args["b"]["default"] == "10"

    def test_function_with_rest_param(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path, "function f(a, ...rest) { return rest; }"
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        args = {a["name"]: a for a in func["args"]}
        assert args["rest"]["kind"] == "vararg"


# ---------------------------------------------------------------------------
# 类与方法提取
# ---------------------------------------------------------------------------


class TestClassExtraction:
    """验证类和方法提取。"""

    def test_class_with_methods(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "class Calc {\n"
            "  constructor(x) { this.x = x; }\n"
            "  add(y) { return this.x + y; }\n"
            "}",
        )
        result = analyzer.analyze(f)
        cls = result["files"][0]["classes"][0]
        assert cls["name"] == "Calc"
        assert len(cls["methods"]) == 2
        assert cls["methods"][0]["name"] == "constructor"
        assert cls["methods"][1]["name"] == "add"
        assert cls["methods"][1]["qualname"] == "Calc.add"

    def test_class_extends(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "class Dog extends Animal {\n"
            "  bark() { return 'woof'; }\n"
            "}",
        )
        result = analyzer.analyze(f)
        cls = result["files"][0]["classes"][0]
        assert cls["name"] == "Dog"
        assert "Animal" in cls["bases"]

    def test_static_method(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "class Foo {\n"
            "  static create(x) { return new Foo(x); }\n"
            "}",
        )
        result = analyzer.analyze(f)
        cls = result["files"][0]["classes"][0]
        assert cls["methods"][0]["name"] == "create"


# ---------------------------------------------------------------------------
# 分支计数
# ---------------------------------------------------------------------------


class TestBranchCounting:
    """验证 JS 分支计数逻辑。"""

    def test_if_statement(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "function f(x) {\n"
            "  if (x > 0) return 1;\n"
            "  return 0;\n"
            "}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["branches"] == 1
        assert func["complexity"] == 2

    def test_for_statement(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "function f() {\n"
            "  for (let i = 0; i < 10; i++) {}\n"
            "  return 0;\n"
            "}",
        )
        result = analyzer.analyze(f)
        assert result["files"][0]["functions"][0]["branches"] == 1

    def test_while_statement(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "function f() {\n  while (true) {}\n  return 0;\n}",
        )
        result = analyzer.analyze(f)
        assert result["files"][0]["functions"][0]["branches"] == 1

    def test_try_catch(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "function f() {\n"
            "  try { return 1; }\n"
            "  catch (e) { return 0; }\n"
            "}",
        )
        result = analyzer.analyze(f)
        # catch_clause = 1 branch
        assert result["files"][0]["functions"][0]["branches"] == 1

    def test_ternary_expression(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "function f(x) {\n  return x > 0 ? x : -x;\n}",
        )
        result = analyzer.analyze(f)
        assert result["files"][0]["functions"][0]["branches"] == 1

    def test_logical_and(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "function f(a, b) {\n  if (a && b) return 1;\n  return 0;\n}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        # 1 if + 1 && = 2
        assert func["branches"] == 2

    def test_logical_or(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "function f(a, b) {\n  if (a || b) return 1;\n  return 0;\n}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        # 1 if + 1 || = 2
        assert func["branches"] == 2

    def test_switch_cases(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "function f(x) {\n"
            "  switch (x) {\n"
            "    case 1: return 1;\n"
            "    case 2: return 2;\n"
            "    default: return 0;\n"
            "  }\n"
            "}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        # 3 switch_case (case 1, case 2, default)
        assert func["branches"] == 3

    def test_nested_function_not_counted(self, analyzer, tmp_path):
        """嵌套函数的分支不计入外层。"""
        f = _write_js(
            tmp_path,
            "function outer() {\n"
            "  if (true) {\n"
            "    function inner() {\n"
            "      if (false) return 1;\n"
            "      for (let i = 0; i < 10; i++) {}\n"
            "    }\n"
            "  }\n"
            "  return 0;\n"
            "}",
        )
        result = analyzer.analyze(f)
        # outer 只有 1 个 if，inner 的 if+for 不计入
        outer = result["files"][0]["functions"][0]
        assert outer["name"] == "outer"
        assert outer["branches"] == 1

    def test_chained_logical_operators(self, analyzer, tmp_path):
        """a && b && c → 2 个决策点。"""
        f = _write_js(
            tmp_path,
            "function f(a, b, c) {\n"
            "  if (a && b && c) return 1;\n"
            "  return 0;\n"
            "}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        # 1 if + 2 && = 3
        assert func["branches"] == 3


# ---------------------------------------------------------------------------
# Import 提取
# ---------------------------------------------------------------------------


class TestImportExtraction:
    """验证 import 和 require 提取。"""

    def test_es_module_import(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "import { foo, bar } from './utils';\n",
        )
        result = analyzer.analyze(f)
        imports = result["files"][0]["imports"]
        assert len(imports) == 1
        assert "import" in imports[0]
        assert "foo" in imports[0]

    def test_require_call(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "const fs = require('fs');\n",
        )
        result = analyzer.analyze(f)
        imports = result["files"][0]["imports"]
        assert len(imports) == 1
        assert "require" in imports[0]

    def test_mixed_imports(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "import { foo } from 'lib';\n"
            "const bar = require('bar');\n",
        )
        result = analyzer.analyze(f)
        imports = result["files"][0]["imports"]
        assert len(imports) == 2


# ---------------------------------------------------------------------------
# 文件收集
# ---------------------------------------------------------------------------


class TestCollectFiles:
    """验证文件收集和排除。"""

    def test_skips_node_modules(self, analyzer, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "index.js").write_text("module.exports = 1;")
        (tmp_path / "app.js").write_text("const x = 1;")
        result = analyzer._collect_files(str(tmp_path))
        nm_prefix = str(nm)
        assert not any(f.startswith(nm_prefix) for f in result)
        assert any("app.js" in f for f in result)

    def test_single_file(self, analyzer, tmp_path):
        f = _write_js(tmp_path, "const x = 1;")
        result = analyzer._collect_files(f)
        assert result == [f]

    def test_non_js_file_returns_empty(self, analyzer, tmp_path):
        f = tmp_path / "readme.txt"
        f.write_text("hello")
        result = analyzer._collect_files(str(f))
        assert result == []


# ---------------------------------------------------------------------------
# 集成测试
# ---------------------------------------------------------------------------


class TestAnalyzeIntegration:
    """验证完整 analyze 流程。"""

    def test_full_file(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "import { calc } from './math';\n"
            "const util = require('util');\n"
            "\n"
            "function divide(a, b = 1) {\n"
            "  if (b === 0) throw new Error('div by zero');\n"
            "  return a / b;\n"
            "}\n"
            "\n"
            "class Calculator {\n"
            "  constructor(x) { this.x = x; }\n"
            "  multiply(factor) {\n"
            "    return this.x > 0 ? this.x * factor : 0;\n"
            "  }\n"
            "}\n"
            "\n"
            "const double = (x) => x * 2;\n",
        )
        result = analyzer.analyze(f)
        assert result["summary"]["total_files"] == 1
        assert result["summary"]["error_files"] == 0
        assert result["summary"]["total_functions"] == 2  # divide, double
        assert result["summary"]["total_classes"] == 1

        # 验证 divide 函数
        divide = result["files"][0]["functions"][0]
        assert divide["name"] == "divide"
        assert divide["branches"] == 1  # 1 if

        # 验证 imports
        imports = result["files"][0]["imports"]
        assert len(imports) == 2

    def test_empty_file(self, analyzer, tmp_path):
        f = _write_js(tmp_path, "")
        result = analyzer.analyze(f)
        assert result["summary"]["total_files"] == 0

    def test_syntax_error_file(self, analyzer, tmp_path):
        f = _write_js(tmp_path, "function f( {\n  return 1;\n}")
        result = analyzer.analyze(f)
        assert result["summary"]["error_files"] == 1
        assert "error" in result["files"][0]


# ---------------------------------------------------------------------------
# gen_cases 集成
# ---------------------------------------------------------------------------


class TestGenCases:
    """验证 gen_cases 返回结构。"""

    def test_returns_test_cases_and_summary(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "function add(a, b) { return a + b; }",
        )
        analysis = analyzer.analyze(f)
        result = analyzer.gen_cases(analysis)
        assert "test_cases" in result
        assert "summary" in result
        assert isinstance(result["test_cases"], list)
        assert len(result["test_cases"]) > 0

    def test_exception_path_generated_when_branches(
        self, analyzer, tmp_path
    ):
        f = _write_js(
            tmp_path,
            "function f(x) {\n  if (x > 0) return 1;\n  return 0;\n}",
        )
        analysis = analyzer.analyze(f)
        result = analyzer.gen_cases(analysis)
        types = {tc["type"] for tc in result["test_cases"]}
        assert "exception_path" in types

    def test_each_case_has_required_fields(self, analyzer, tmp_path):
        f = _write_js(
            tmp_path,
            "function f(a, b) { return a + b; }",
        )
        analysis = analyzer.analyze(f)
        result = analyzer.gen_cases(analysis)
        for tc in result["test_cases"]:
            assert "target" in tc
            assert "type" in tc
            assert "description" in tc
            assert "inputs" in tc
            assert "expected" in tc
