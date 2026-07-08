# -*- coding: utf-8 -*-
"""Rust 适配器测试 - 验证 tree-sitter Rust AST 分析。

测试函数提取、impl 方法、struct、分支计数、use 导入、async、文件收集。
"""
import os

import pytest

from lang import get_analyzer


@pytest.fixture
def analyzer():
    return get_analyzer("rust")


def _write_rs(tmp_path, code, name="sample.rs"):
    """写 Rust 文件并返回路径。"""
    f = tmp_path / name
    f.write_text(code)
    return str(f)


# ---------------------------------------------------------------------------
# 函数提取
# ---------------------------------------------------------------------------


class TestFunctionExtraction:
    """验证函数声明提取。"""

    def test_function_declaration(self, analyzer, tmp_path):
        f = _write_rs(tmp_path, "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}")
        result = analyzer.analyze(f)
        assert result["summary"]["total_functions"] == 1
        func = result["files"][0]["functions"][0]
        assert func["name"] == "add"
        assert len(func["args"]) == 2
        assert func["is_async"] is False

    def test_async_function(self, analyzer, tmp_path):
        f = _write_rs(
            tmp_path,
            "async fn fetch_data(url: &str) -> String {\n    String::new()\n}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["name"] == "fetch_data"
        assert func["is_async"] is True

    def test_function_with_self_param(self, analyzer, tmp_path):
        """fn process(&self) -> i32。"""
        f = _write_rs(
            tmp_path,
            "struct Counter;\n\n"
            "impl Counter {\n"
            "    fn get(&self) -> i32 {\n        0\n    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        funcs = result["files"][0]["functions"]
        method = [f for f in funcs if f["name"] == "get"][0]
        assert "self" in method["args"][0]["name"]

    def test_function_with_ref_param(self, analyzer, tmp_path):
        """fn process(data: &str) -> usize。"""
        f = _write_rs(
            tmp_path,
            "fn process(data: &str) -> usize {\n    data.len()\n}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["args"][0]["name"] == "data"
        assert "str" in func["args"][0]["annotation"]

    def test_function_return_type(self, analyzer, tmp_path):
        f = _write_rs(tmp_path, "fn foo() -> i32 {\n    42\n}")
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["returns"] is not None
        assert "i32" in func["returns"]

    def test_function_no_return(self, analyzer, tmp_path):
        f = _write_rs(tmp_path, "fn foo() {\n    println!(\"hi\")\n}")
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["returns"] is None


# ---------------------------------------------------------------------------
# impl 方法提取
# ---------------------------------------------------------------------------


class TestImplExtraction:
    """验证 impl 块中方法提取。"""

    def test_impl_methods_extracted(self, analyzer, tmp_path):
        f = _write_rs(
            tmp_path,
            "struct Calculator {\n    x: i32,\n}\n\n"
            "impl Calculator {\n"
            "    fn new(x: i32) -> Self {\n        Self { x }\n    }\n"
            "    fn add(&self, y: i32) -> i32 {\n        self.x + y\n    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        funcs = result["files"][0]["functions"]
        assert len(funcs) >= 2
        # qualname 应包含类型名
        new_fn = [f for f in funcs if f["name"] == "new"][0]
        assert "Calculator" in new_fn["qualname"]
        add_fn = [f for f in funcs if f["name"] == "add"][0]
        assert "Calculator" in add_fn["qualname"]


# ---------------------------------------------------------------------------
# Struct 提取
# ---------------------------------------------------------------------------


class TestStructExtraction:
    """验证 struct 提取。"""

    def test_struct_declaration(self, analyzer, tmp_path):
        f = _write_rs(tmp_path, "struct Point {\n    x: f64,\n    y: f64,\n}")
        result = analyzer.analyze(f)
        assert result["summary"]["total_classes"] == 1
        cls = result["files"][0]["classes"][0]
        assert cls["name"] == "Point"

    def test_tuple_struct(self, analyzer, tmp_path):
        f = _write_rs(tmp_path, "struct Color(i32, i32, i32);")
        result = analyzer.analyze(f)
        assert result["summary"]["total_classes"] >= 1


# ---------------------------------------------------------------------------
# 分支计数
# ---------------------------------------------------------------------------


class TestBranchCounting:
    """验证 Rust 分支计数。"""

    def test_if_statement(self, analyzer, tmp_path):
        f = _write_rs(
            tmp_path,
            "fn f(x: i32) -> i32 {\n    if x > 0 { 1 } else { 0 }\n}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        assert func["branches"] == 1
        assert func["complexity"] == 2

    def test_for_loop(self, analyzer, tmp_path):
        f = _write_rs(
            tmp_path,
            "fn f() {\n    for i in 0..10 {\n        println!(\"{}\", i)\n    }\n}",
        )
        result = analyzer.analyze(f)
        assert result["files"][0]["functions"][0]["branches"] == 1

    def test_while_loop(self, analyzer, tmp_path):
        f = _write_rs(
            tmp_path,
            "fn f() {\n    let mut x = 10;\n    while x > 0 { x -= 1; }\n}",
        )
        result = analyzer.analyze(f)
        assert result["files"][0]["functions"][0]["branches"] == 1

    def test_match_expression(self, analyzer, tmp_path):
        f = _write_rs(
            tmp_path,
            "fn f(x: i32) -> i32 {\n"
            "    match x {\n"
            "        1 => 1,\n"
            "        2 => 2,\n"
            "        _ => 0,\n"
            "    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        func = result["files"][0]["functions"][0]
        # 1 match + match_arm 计数
        assert func["branches"] >= 1

    def test_nested_function_not_counted(self, analyzer, tmp_path):
        """嵌套函数的分支不计入外层。"""
        f = _write_rs(
            tmp_path,
            "fn outer() {\n"
            "    if true {\n"
            "        fn inner() {\n"
            "            if false { return; }\n"
            "        }\n"
            "    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        outer = result["files"][0]["functions"][0]
        assert outer["name"] == "outer"
        # outer 只有 1 个 if
        assert outer["branches"] == 1


# ---------------------------------------------------------------------------
# use 导入提取
# ---------------------------------------------------------------------------


class TestImportExtraction:
    """验证 use 导入提取。"""

    def test_use_declaration(self, analyzer, tmp_path):
        f = _write_rs(tmp_path, "use std::collections::HashMap;\n\nfn main() {}")
        result = analyzer.analyze(f)
        imports = result["files"][0]["imports"]
        assert len(imports) == 1
        assert "HashMap" in imports[0]

    def test_multiple_use_declarations(self, analyzer, tmp_path):
        f = _write_rs(
            tmp_path,
            "use std::io;\nuse std::fs;\n\nfn main() {}",
        )
        result = analyzer.analyze(f)
        imports = result["files"][0]["imports"]
        assert len(imports) == 2


# ---------------------------------------------------------------------------
# 文件收集
# ---------------------------------------------------------------------------


class TestCollectFiles:
    """验证文件收集和排除。"""

    def test_skips_target_dir(self, analyzer, tmp_path):
        target = tmp_path / "target"
        target.mkdir()
        (target / "build.rs").write_text("fn main() {}")
        (tmp_path / "app.rs").write_text("fn main() {}")
        result = analyzer._collect_files(str(tmp_path))
        # 检查路径组件，避免 tmp_path 目录名含 "target" 导致误判
        target_files = [
            f for f in result
            if os.path.split(f)[0] == str(target)
        ]
        assert len(target_files) == 0
        assert any("app.rs" in f for f in result)

    def test_non_rs_file_returns_empty(self, analyzer, tmp_path):
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
        f = _write_rs(
            tmp_path,
            "use std::fmt;\n\n"
            "fn divide(a: f64, b: f64) -> Result<f64, String> {\n"
            "    if b == 0.0 {\n"
            '        return Err(String::from("div by zero"));\n'
            "    }\n"
            "    Ok(a / b)\n"
            "}\n\n"
            "struct Calculator {\n    x: f64,\n}\n\n"
            "impl Calculator {\n"
            "    fn divide(&self, b: f64) -> Result<f64, String> {\n"
            "        divide(self.x, b)\n"
            "    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        assert result["summary"]["total_files"] == 1
        assert result["summary"]["error_files"] == 0
        assert result["summary"]["total_functions"] == 2  # divide + divide
        assert result["summary"]["total_classes"] == 1

    def test_empty_file(self, analyzer, tmp_path):
        f = tmp_path / "empty.rs"
        f.write_text("")
        result = analyzer.analyze(str(f))
        assert result["summary"]["total_files"] == 0

    def test_syntax_error_file(self, analyzer, tmp_path):
        f = _write_rs(tmp_path, "fn f( {\n    42\n}")
        result = analyzer.analyze(f)
        assert result["summary"]["error_files"] == 1
        assert "error" in result["files"][0]


# ---------------------------------------------------------------------------
# gen_cases 集成
# ---------------------------------------------------------------------------


class TestGenCases:
    """验证 gen_cases 返回结构。"""

    def test_returns_test_cases_and_summary(self, analyzer, tmp_path):
        f = _write_rs(tmp_path, "fn add(a: i32, b: i32) -> i32 {\n    a + b\n}")
        analysis = analyzer.analyze(f)
        result = analyzer.gen_cases(analysis)
        assert "test_cases" in result
        assert "summary" in result
        assert len(result["test_cases"]) > 0

    def test_exception_path_generated_when_branches(self, analyzer, tmp_path):
        f = _write_rs(
            tmp_path,
            "fn f(x: i32) -> i32 {\n    if x > 0 { 1 } else { 0 }\n}",
        )
        analysis = analyzer.analyze(f)
        result = analyzer.gen_cases(analysis)
        types = {tc["type"] for tc in result["test_cases"]}
        assert "exception_path" in types
