# -*- coding: utf-8 -*-
"""TypeScript 适配器测试 - 验证 tree-sitter TypeScript AST 分析。

测试类型注解、required/optional 参数、interface、export、分支计数。
"""
import os

import pytest

from lang import get_analyzer


@pytest.fixture
def analyzer():
    return get_analyzer("typescript")


def _write_ts(tmp_path, code, name="sample.ts"):
    """写 TS 文件并返回路径。"""
    f = tmp_path / name
    f.write_text(code)
    return str(f)


# ---------------------------------------------------------------------------
# 函数提取
# ---------------------------------------------------------------------------


class TestFunctionExtraction:
    """验证函数声明和箭头函数提取。"""

    def test_function_with_typed_params(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "function add(a: number, b: number): number {\n"
            "    return a + b;\n"
            "}",
        )
        result = analyzer.analyze(f)
        assert result["summary"]["total_functions"] == 1
        func = result["files"][0]["functions"][0]
        assert func["name"] == "add"
        assert len(func["args"]) == 2
        assert func["args"][0]["annotation"] == "number"
        assert func["returns"] == "number"

    def test_optional_parameter(self, analyzer, tmp_path):
        """optional_parameter: b?: number。"""
        f = _write_ts(
            tmp_path,
            "function f(a: number, b?: number): number {\n"
            "    return a;\n"
            "}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        args = {a["name"]: a for a in func["args"]}
        assert args["a"]["annotation"] == "number"
        assert args["b"]["annotation"] == "number"

    def test_arrow_function_with_types(self, analyzer, tmp_path):
        f = _write_ts(tmp_path, "const add = (a: number, b: number): number => a + b;")
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["name"] == "add"
        assert len(func["args"]) == 2
        assert func["args"][0]["annotation"] == "number"

    def test_async_function(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "async function fetchData(url: string): Promise<string> {\n"
            "    return fetch(url);\n"
            "}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["name"] == "fetchData"
        assert func["is_async"] is True

    def test_function_with_default_param(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "function f(a: number, b: number = 10): number {\n"
            "    return a + b;\n"
            "}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        args = {a["name"]: a for a in func["args"]}
        assert args["b"]["has_default"] is True

    def test_rest_parameter(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "function f(a: number, ...rest: number[]): number {\n"
            "    return a;\n"
            "}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        args = {a["name"]: a for a in func["args"]}
        assert args["rest"]["kind"] == "vararg"


# ---------------------------------------------------------------------------
# Class 和 Interface 提取
# ---------------------------------------------------------------------------


class TestClassExtraction:
    """验证 class 和 interface 提取。"""

    def test_class_with_methods(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "class Calculator {\n"
            "    constructor(private x: number) {}\n"
            "    add(y: number): number { return this.x + y; }\n"
            "}",
        )
        result = analyzer.analyze(f)
        cls = result["files"][0]["classes"][0]
        assert cls["name"] == "Calculator"
        assert len(cls["methods"]) >= 2

    def test_class_extends(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "class Dog extends Animal {\n"
            "    bark(): string { return 'woof'; }\n"
            "}",
        )
        result = analyzer.analyze(f)
        cls = result["files"][0]["classes"][0]
        assert cls["name"] == "Dog"
        assert "Animal" in cls["bases"]

    def test_class_implements(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "class Foo implements IFoo {\n"
            "    bar(): void {}\n"
            "}",
        )
        result = analyzer.analyze(f)
        cls = result["files"][0]["classes"][0]
        assert "IFoo" in cls["bases"]


# ---------------------------------------------------------------------------
# export 提取
# ---------------------------------------------------------------------------


class TestExportExtraction:
    """验证 export 语句中的函数和类提取。"""

    def test_export_function(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "export function add(a: number, b: number): number {\n"
            "    return a + b;\n"
            "}",
        )
        result = analyzer.analyze(f)
        assert result["summary"]["total_functions"] == 1
        func = result["files"][0]["functions"][0]
        assert func["name"] == "add"

    def test_export_class(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "export class Foo {\n    bar(): void {}\n}",
        )
        result = analyzer.analyze(f)
        assert result["summary"]["total_classes"] == 1
        cls = result["files"][0]["classes"][0]
        assert cls["name"] == "Foo"

    def test_export_const_arrow(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "export const double = (x: number): number => x * 2;",
        )
        result = analyzer.analyze(f)
        assert result["summary"]["total_functions"] == 1
        func = result["files"][0]["functions"][0]
        assert func["name"] == "double"


# ---------------------------------------------------------------------------
# 分支计数
# ---------------------------------------------------------------------------


class TestBranchCounting:
    """验证 TS 分支计数。"""

    def test_if_statement(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "function f(x: number): number {\n"
            "    if (x > 0) return 1;\n"
            "    return 0;\n"
            "}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["branches"] == 1
        assert func["complexity"] == 2

    def test_for_statement(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "function f(): number {\n"
            "    for (let i = 0; i < 10; i++) {}\n"
            "    return 0;\n"
            "}",
        )
        result = analyzer.analyze(f)
        assert result["files"][0]["functions"][0]["branches"] == 1

    def test_try_catch(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "function f(): number {\n"
            "    try { return 1; }\n"
            "    catch (e) { return 0; }\n"
            "}",
        )
        result = analyzer.analyze(f)
        assert result["files"][0]["functions"][0]["branches"] == 1

    def test_ternary_expression(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "function f(x: number): number {\n"
            "    return x > 0 ? x : -x;\n"
            "}",
        )
        result = analyzer.analyze(f)
        assert result["files"][0]["functions"][0]["branches"] == 1

    def test_logical_and(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "function f(a: boolean, b: boolean): number {\n"
            "    if (a && b) return 1;\n"
            "    return 0;\n"
            "}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        # 1 if + 1 && = 2
        assert func["branches"] == 2

    def test_nested_function_not_counted(self, analyzer, tmp_path):
        """嵌套函数的分支不计入外层。"""
        f = _write_ts(
            tmp_path,
            "function outer(): number {\n"
            "    if (true) {\n"
            "        function inner(): number {\n"
            "            if (false) return 1;\n"
            "            return 0;\n"
            "        }\n"
            "    }\n"
            "    return 0;\n"
            "}",
        )
        result = analyzer.analyze(f)
        outer = result["files"][0]["functions"][0]
        assert outer["name"] == "outer"
        assert outer["branches"] == 1


# ---------------------------------------------------------------------------
# Import 提取
# ---------------------------------------------------------------------------


class TestImportExtraction:
    """验证 import 提取。"""

    def test_es_module_import(self, analyzer, tmp_path):
        f = _write_ts(tmp_path, "import { foo, bar } from './utils';\n")
        result = analyzer.analyze(f)
        imports = result["files"][0]["imports"]
        assert len(imports) == 1
        assert "foo" in imports[0]

    def test_require_call(self, analyzer, tmp_path):
        f = _write_ts(tmp_path, "const fs = require('fs');\n")
        result = analyzer.analyze(f)
        imports = result["files"][0]["imports"]
        assert len(imports) == 1
        assert "require" in imports[0]


# ---------------------------------------------------------------------------
# 文件收集
# ---------------------------------------------------------------------------


class TestCollectFiles:
    """验证文件收集和排除。"""

    def test_skips_node_modules(self, analyzer, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "index.ts").write_text("export const x = 1;")
        (tmp_path / "app.ts").write_text("const x = 1;")
        result = analyzer._collect_files(str(tmp_path))
        # 检查路径组件，避免 tmp_path 目录名含 "node_modules" 导致误判
        nm_files = [
            f for f in result
            if os.path.split(f)[0] == str(nm)
        ]
        assert len(nm_files) == 0
        assert any("app.ts" in f for f in result)

    def test_skips_declaration_files(self, analyzer, tmp_path):
        """.d.ts 文件不被收集。"""
        (tmp_path / "app.ts").write_text("const x = 1;")
        (tmp_path / "app.d.ts").write_text("declare const x: number;")
        result = analyzer._collect_files(str(tmp_path))
        assert len(result) == 1
        assert "app.ts" in result[0]

    def test_non_ts_file_returns_empty(self, analyzer, tmp_path):
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
        f = _write_ts(
            tmp_path,
            "import { calc } from './math';\n\n"
            "export function divide(a: number, b: number = 1): number {\n"
            "    if (b === 0) throw new Error('div by zero');\n"
            "    return a / b;\n"
            "}\n\n"
            "export class Calculator {\n"
            "    constructor(private x: number) {}\n"
            "    multiply(factor: number): number {\n"
            "        return this.x > 0 ? this.x * factor : 0;\n"
            "    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        assert result["summary"]["total_files"] == 1
        assert result["summary"]["error_files"] == 0
        # divide 是顶层函数，multiply 是 class 方法（计入 classes.methods）
        assert result["summary"]["total_functions"] == 1
        assert result["summary"]["total_classes"] == 1

    def test_empty_file(self, analyzer, tmp_path):
        f = tmp_path / "empty.ts"
        f.write_text("")
        result = analyzer.analyze(str(f))
        assert result["summary"]["total_files"] == 0

    def test_syntax_error_file(self, analyzer, tmp_path):
        f = _write_ts(tmp_path, "function f( {\n    return 1;\n}")
        result = analyzer.analyze(f)
        assert result["summary"]["error_files"] == 1
        assert "error" in result["files"][0]


# ---------------------------------------------------------------------------
# gen_cases 集成
# ---------------------------------------------------------------------------


class TestGenCases:
    """验证 gen_cases 返回结构。"""

    def test_returns_test_cases_and_summary(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "function add(a: number, b: number): number {\n    return a + b;\n}",
        )
        analysis = analyzer.analyze(f)
        result = analyzer.gen_cases(analysis)
        assert "test_cases" in result
        assert "summary" in result
        assert len(result["test_cases"]) > 0

    def test_exception_path_generated_when_branches(self, analyzer, tmp_path):
        f = _write_ts(
            tmp_path,
            "function f(x: number): number {\n"
            "    if (x > 0) return 1;\n"
            "    return 0;\n"
            "}",
        )
        analysis = analyzer.analyze(f)
        result = analyzer.gen_cases(analysis)
        types = {tc["type"] for tc in result["test_cases"]}
        assert "exception_path" in types
