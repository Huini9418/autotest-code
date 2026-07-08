# -*- coding: utf-8 -*-
"""Go 适配器测试 - 验证 tree-sitter Go AST 分析。

测试函数提取、方法（receiver）、struct、分支计数、import、文件收集。
"""
import os

import pytest

from lang import get_analyzer


@pytest.fixture
def analyzer():
    return get_analyzer("go")


def _write_go(tmp_path, code, name="sample.go", pkg="main"):
    """写 Go 文件并返回路径。"""
    f = tmp_path / name
    f.write_text(f"package {pkg}\n\n{code}")
    return str(f)


# ---------------------------------------------------------------------------
# 函数提取
# ---------------------------------------------------------------------------


class TestFunctionExtraction:
    """验证函数声明提取。"""

    def test_function_declaration(self, analyzer, tmp_path):
        f = _write_go(tmp_path, "func add(a int, b int) int {\n    return a + b\n}")
        result = analyzer.analyze(f)
        assert result["summary"]["total_functions"] == 1
        func = result["files"][0]["functions"][0]
        assert func["name"] == "add"
        assert len(func["args"]) == 2
        assert func["is_async"] is False

    def test_function_with_shared_type(self, analyzer, tmp_path):
        """Go 多参数共享类型：func foo(a, b int)。"""
        f = _write_go(tmp_path, "func foo(a, b int) int {\n    return a + b\n}")
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert len(func["args"]) == 2
        assert func["args"][0]["name"] == "a"
        assert func["args"][1]["name"] == "b"
        assert "int" in func["args"][0]["annotation"]

    def test_function_with_variadic(self, analyzer, tmp_path):
        """可变参数：func process(items ...string)。"""
        f = _write_go(
            tmp_path,
            "func process(items ...string) int {\n    return len(items)\n}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert len(func["args"]) == 1
        assert func["args"][0]["kind"] == "vararg"

    def test_function_return_single(self, analyzer, tmp_path):
        """单返回值。"""
        f = _write_go(tmp_path, "func foo() int {\n    return 42\n}")
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["returns"] is not None

    def test_function_return_multiple(self, analyzer, tmp_path):
        """多返回值：func divide(a, b float64) (float64, error)。"""
        f = _write_go(
            tmp_path,
            "func divide(a, b float64) (float64, error) {\n    return a / b, nil\n}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["returns"] is not None
        assert "float64" in func["returns"]
        assert "error" in func["returns"]

    def test_function_no_return(self, analyzer, tmp_path):
        """无返回值。"""
        f = _write_go(tmp_path, "func foo() {\n    var _ = 1\n}")
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["returns"] is None


# ---------------------------------------------------------------------------
# 方法（receiver）提取
# ---------------------------------------------------------------------------


class TestMethodExtraction:
    """验证带 receiver 的方法提取。"""

    def test_method_with_pointer_receiver(self, analyzer, tmp_path):
        """func (c *Calculator) GetX() int。"""
        f = _write_go(
            tmp_path,
            "type Calculator struct {\n    x int\n}\n\n"
            "func (c *Calculator) GetX() int {\n    return c.x\n}",
        )
        result = analyzer.analyze(f)
        # struct + method 都提取了
        assert result["summary"]["total_classes"] >= 1
        funcs = result["files"][0]["functions"]
        method = [f for f in funcs if f["name"] == "GetX"][0]
        assert "Calculator" in method["qualname"]

    def test_method_with_value_receiver(self, analyzer, tmp_path):
        """func (c Calculator) Area() float64。"""
        f = _write_go(
            tmp_path,
            "type Shape struct {\n    w float64\n}\n\n"
            "func (s Shape) Area() float64 {\n    return s.w\n}",
        )
        result = analyzer.analyze(f)
        funcs = result["files"][0]["functions"]
        method = [f for f in funcs if f["name"] == "Area"][0]
        assert "Shape" in method["qualname"]


# ---------------------------------------------------------------------------
# Struct 提取
# ---------------------------------------------------------------------------


class TestStructExtraction:
    """验证 struct 提取。"""

    def test_struct_declaration(self, analyzer, tmp_path):
        f = _write_go(
            tmp_path,
            "type Point struct {\n    X int\n    Y int\n}",
        )
        result = analyzer.analyze(f)
        assert result["summary"]["total_classes"] == 1
        cls = result["files"][0]["classes"][0]
        assert cls["name"] == "Point"

    def test_multiple_structs(self, analyzer, tmp_path):
        f = _write_go(
            tmp_path,
            "type Foo struct {\n    a int\n}\n\n"
            "type Bar struct {\n    b string\n}",
        )
        result = analyzer.analyze(f)
        assert result["summary"]["total_classes"] == 2


# ---------------------------------------------------------------------------
# 分支计数
# ---------------------------------------------------------------------------


class TestBranchCounting:
    """验证 Go 分支计数。"""

    def test_if_statement(self, analyzer, tmp_path):
        f = _write_go(
            tmp_path,
            "func f(x int) int {\n    if x > 0 {\n        return 1\n    }\n    return 0\n}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["branches"] == 1
        assert func["complexity"] == 2

    def test_for_statement(self, analyzer, tmp_path):
        f = _write_go(
            tmp_path,
            "func f() int {\n    for i := 0; i < 10; i++ {\n    }\n    return 0\n}",
        )
        result = analyzer.analyze(f)
        assert result["files"][0]["functions"][0]["branches"] == 1

    def test_switch_statement(self, analyzer, tmp_path):
        f = _write_go(
            tmp_path,
            "func f(x int) int {\n"
            "    switch x {\n"
            "    case 1: return 1\n"
            "    case 2: return 2\n"
            "    default: return 0\n"
            "    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        # 1 switch + 3 case_clause = 4
        assert func["branches"] >= 3

    def test_nested_function_not_counted(self, analyzer, tmp_path):
        """嵌套 func literal 的分支不计入外层。"""
        f = _write_go(
            tmp_path,
            "func outer() {\n"
            "    if true {\n"
            "        f := func() {\n"
            "            if false { return }\n"
            "            for i := 0; i < 5; i++ {}\n"
            "        }\n"
            "        _ = f\n"
            "    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        outer = result["files"][0]["functions"][0]
        assert outer["name"] == "outer"
        # outer 只有 1 个 if，func literal 的分支不计入
        assert outer["branches"] == 1


# ---------------------------------------------------------------------------
# Import 提取
# ---------------------------------------------------------------------------


class TestImportExtraction:
    """验证 import 提取。"""

    def test_single_import(self, analyzer, tmp_path):
        f = _write_go(
            tmp_path,
            'import "fmt"\n\nfunc main() {\n    fmt.Println("hi")\n}',
        )
        result = analyzer.analyze(f)
        imports = result["files"][0]["imports"]
        assert len(imports) == 1
        assert "fmt" in imports[0]

    def test_import_group(self, analyzer, tmp_path):
        f = _write_go(
            tmp_path,
            'import (\n    "fmt"\n    "os"\n)\n\nfunc main() {}',
        )
        result = analyzer.analyze(f)
        imports = result["files"][0]["imports"]
        assert len(imports) >= 1
        combined = " ".join(imports)
        assert "fmt" in combined
        assert "os" in combined


# ---------------------------------------------------------------------------
# 文件收集
# ---------------------------------------------------------------------------


class TestCollectFiles:
    """验证文件收集和排除。"""

    def test_skips_vendor(self, analyzer, tmp_path):
        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "lib.go").write_text("package lib\n")
        (tmp_path / "app.go").write_text("package main\n")
        result = analyzer._collect_files(str(tmp_path))
        # 检查路径组件，避免 tmp_path 目录名含 "vendor" 导致误判
        vendor_files = [
            f for f in result
            if os.path.split(f)[0] == str(vendor)
        ]
        assert len(vendor_files) == 0
        assert any("app.go" in f for f in result)

    def test_skips_test_files(self, analyzer, tmp_path):
        """_test.go 文件不被收集。"""
        (tmp_path / "app.go").write_text("package main\n")
        (tmp_path / "app_test.go").write_text("package main\n")
        result = analyzer._collect_files(str(tmp_path))
        assert len(result) == 1
        assert "app.go" in result[0]

    def test_non_go_file_returns_empty(self, analyzer, tmp_path):
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
        f = _write_go(
            tmp_path,
            'import "fmt"\n\n'
            "func divide(a, b float64) (float64, error) {\n"
            "    if b == 0 {\n"
            '        return 0, fmt.Errorf("div by zero")\n'
            "    }\n"
            "    return a / b, nil\n"
            "}\n\n"
            "type Calculator struct {\n"
            "    result float64\n"
            "}\n\n"
            "func (c *Calculator) Divide(a, b float64) (float64, error) {\n"
            "    return divide(a, b)\n"
            "}",
        )
        result = analyzer.analyze(f)
        assert result["summary"]["total_files"] == 1
        assert result["summary"]["error_files"] == 0
        assert result["summary"]["total_functions"] == 2  # divide + Divide
        assert result["summary"]["total_classes"] == 1

    def test_empty_file(self, analyzer, tmp_path):
        f = tmp_path / "empty.go"
        f.write_text("")
        result = analyzer.analyze(str(f))
        assert result["summary"]["total_files"] == 0

    def test_syntax_error_file(self, analyzer, tmp_path):
        f = _write_go(tmp_path, "func f( {\n    return 1\n}")
        result = analyzer.analyze(f)
        assert result["summary"]["error_files"] == 1
        assert "error" in result["files"][0]


# ---------------------------------------------------------------------------
# gen_cases 集成
# ---------------------------------------------------------------------------


class TestGenCases:
    """验证 gen_cases 返回结构。"""

    def test_returns_test_cases_and_summary(self, analyzer, tmp_path):
        f = _write_go(tmp_path, "func add(a int, b int) int {\n    return a + b\n}")
        analysis = analyzer.analyze(f)
        result = analyzer.gen_cases(analysis)
        assert "test_cases" in result
        assert "summary" in result
        assert len(result["test_cases"]) > 0

    def test_exception_path_generated_when_branches(self, analyzer, tmp_path):
        f = _write_go(
            tmp_path,
            "func f(x int) int {\n    if x > 0 { return 1 }\n    return 0\n}",
        )
        analysis = analyzer.analyze(f)
        result = analyzer.gen_cases(analysis)
        types = {tc["type"] for tc in result["test_cases"]}
        assert "exception_path" in types
