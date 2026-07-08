# -*- coding: utf-8 -*-
"""Java 适配器测试 - 验证 tree-sitter Java AST 分析。

测试方法提取、class/interface/enum、分支计数、import、修饰符、文件收集。
"""
import os

import pytest

from lang import get_analyzer


@pytest.fixture
def analyzer():
    return get_analyzer("java")


def _write_java(tmp_path, code, name="Sample.java"):
    """写 Java 文件并返回路径。"""
    f = tmp_path / name
    f.write_text(code)
    return str(f)


# ---------------------------------------------------------------------------
# 类与方法提取
# ---------------------------------------------------------------------------


class TestClassExtraction:
    """验证 class/interface/enum 提取。"""

    def test_class_with_methods(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Calc {\n"
            "    public int add(int a, int b) {\n        return a + b;\n    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        assert result["summary"]["total_classes"] == 1
        cls = result["files"][0]["classes"][0]
        assert cls["name"] == "Calc"
        assert len(cls["methods"]) == 1
        assert cls["methods"][0]["name"] == "add"
        assert cls["methods"][0]["qualname"] == "Calc.add"

    def test_class_extends(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Dog extends Animal {\n"
            "    public void bark() {}\n"
            "}",
        )
        result = analyzer.analyze(f)
        cls = result["files"][0]["classes"][0]
        assert cls["name"] == "Dog"
        assert "Animal" in cls["bases"]

    def test_class_implements(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Foo implements Runnable {\n"
            "    public void run() {}\n"
            "}",
        )
        result = analyzer.analyze(f)
        cls = result["files"][0]["classes"][0]
        assert "Runnable" in cls["bases"]

    def test_interface_declaration(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public interface Shape {\n    double area();\n}",
        )
        result = analyzer.analyze(f)
        assert result["summary"]["total_classes"] >= 1
        cls = result["files"][0]["classes"][0]
        assert cls["name"] == "Shape"

    def test_enum_declaration(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public enum Color {\n    RED, GREEN, BLUE\n}",
        )
        result = analyzer.analyze(f)
        cls = result["files"][0]["classes"][0]
        assert cls["name"] == "Color"

    def test_constructor_extracted(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Foo {\n"
            "    public Foo(int x) {}\n"
            "}",
        )
        result = analyzer.analyze(f)
        cls = result["files"][0]["classes"][0]
        assert any(m["name"] == "Foo" for m in cls["methods"])


# ---------------------------------------------------------------------------
# 方法签名提取
# ---------------------------------------------------------------------------


class TestMethodSignature:
    """验证方法参数和返回类型提取。"""

    def test_method_params(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Foo {\n"
            "    public int add(int a, int b) { return a + b; }\n"
            "}",
        )
        result = analyzer.analyze(f)
        method = result["files"][0]["classes"][0]["methods"][0]
        assert len(method["args"]) == 2
        assert method["args"][0]["name"] == "a"
        assert "int" in method["args"][0]["annotation"]

    def test_method_return_type(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Foo {\n"
            "    public String getName() { return \"\"; }\n"
            "}",
        )
        result = analyzer.analyze(f)
        method = result["files"][0]["classes"][0]["methods"][0]
        assert method["returns"] is not None
        assert "String" in method["returns"]

    def test_void_method(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Foo {\n    public void run() {}\n}",
        )
        result = analyzer.analyze(f)
        method = result["files"][0]["classes"][0]["methods"][0]
        assert "void" in (method["returns"] or "")

    def test_static_method(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Foo {\n"
            "    public static int create() { return 0; }\n"
            "}",
        )
        result = analyzer.analyze(f)
        method = result["files"][0]["classes"][0]["methods"][0]
        assert method["is_static"] is True

    def test_vararg_param(self, analyzer, tmp_path):
        """String... args。"""
        f = _write_java(
            tmp_path,
            "public class Foo {\n"
            "    public void process(String... args) {}\n"
            "}",
        )
        result = analyzer.analyze(f)
        method = result["files"][0]["classes"][0]["methods"][0]
        assert len(method["args"]) == 1
        assert method["args"][0]["kind"] == "vararg"


# ---------------------------------------------------------------------------
# 分支计数
# ---------------------------------------------------------------------------


class TestBranchCounting:
    """验证 Java 分支计数。"""

    def test_if_statement(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Foo {\n"
            "    public int f(int x) {\n"
            "        if (x > 0) return 1;\n"
            "        return 0;\n"
            "    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        method = result["files"][0]["classes"][0]["methods"][0]
        assert method["branches"] == 1
        assert method["complexity"] == 2

    def test_for_statement(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Foo {\n"
            "    public void f() {\n"
            "        for (int i = 0; i < 10; i++) {}\n"
            "    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        method = result["files"][0]["classes"][0]["methods"][0]
        assert method["branches"] == 1

    def test_while_statement(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Foo {\n"
            "    public void f() {\n        while (true) {}\n    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        method = result["files"][0]["classes"][0]["methods"][0]
        assert method["branches"] == 1

    def test_try_catch(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Foo {\n"
            "    public int f() {\n"
            "        try { return 1; }\n"
            "        catch (Exception e) { return 0; }\n"
            "    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        method = result["files"][0]["classes"][0]["methods"][0]
        # catch_clause = 1 branch
        assert method["branches"] == 1

    def test_switch_expression(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Foo {\n"
            "    public int f(int x) {\n"
            "        switch (x) {\n"
            "            case 1: return 1;\n"
            "            case 2: return 2;\n"
            "            default: return 0;\n"
            "        }\n"
            "    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        method = result["files"][0]["classes"][0]["methods"][0]
        assert method["branches"] >= 3

    def test_nested_method_not_counted(self, analyzer, tmp_path):
        """嵌套类的方法分支不计入外层。"""
        f = _write_java(
            tmp_path,
            "public class Outer {\n"
            "    public void f() {\n"
            "        if (true) {\n"
            "            class Inner {\n"
            "                void g() { if (false) {} }\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        outer_method = result["files"][0]["classes"][0]["methods"][0]
        assert outer_method["name"] == "f"
        # Outer.f 只有 1 个 if，Inner 的 if 不计入
        assert outer_method["branches"] == 1


# ---------------------------------------------------------------------------
# Import 提取
# ---------------------------------------------------------------------------


class TestImportExtraction:
    """验证 import 提取。"""

    def test_import_declaration(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "import java.util.List;\n\n"
            "public class Foo {\n}",
        )
        result = analyzer.analyze(f)
        imports = result["files"][0]["imports"]
        assert len(imports) == 1
        assert "List" in imports[0]

    def test_multiple_imports(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "import java.util.List;\n"
            "import java.util.Map;\n\n"
            "public class Foo {\n}",
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
        (target / "Build.java").write_text("class Build {}")
        (tmp_path / "App.java").write_text("class App {}")
        result = analyzer._collect_files(str(tmp_path))
        # 检查路径组件，避免 tmp_path 目录名含 "target" 导致误判
        target_files = [
            f for f in result
            if os.path.split(f)[0] == str(target)
        ]
        assert len(target_files) == 0
        assert any("App.java" in f for f in result)

    def test_non_java_file_returns_empty(self, analyzer, tmp_path):
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
        f = _write_java(
            tmp_path,
            "import java.util.List;\n\n"
            "public class Calculator {\n"
            "    public double divide(double a, double b) {\n"
            "        if (b == 0) throw new IllegalArgumentException();\n"
            "        return a / b;\n"
            "    }\n"
            "    public static Calculator create() {\n"
            "        return new Calculator();\n"
            "    }\n"
            "}",
        )
        result = analyzer.analyze(f)
        assert result["summary"]["total_files"] == 1
        assert result["summary"]["error_files"] == 0
        assert result["summary"]["total_classes"] == 1
        cls = result["files"][0]["classes"][0]
        assert len(cls["methods"]) == 2

    def test_empty_file(self, analyzer, tmp_path):
        f = tmp_path / "Empty.java"
        f.write_text("")
        result = analyzer.analyze(str(f))
        assert result["summary"]["total_files"] == 0

    def test_syntax_error_file(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Foo {\n    public void f( {\n    }\n}",
        )
        result = analyzer.analyze(f)
        assert result["summary"]["error_files"] == 1
        assert "error" in result["files"][0]


# ---------------------------------------------------------------------------
# gen_cases 集成
# ---------------------------------------------------------------------------


class TestGenCases:
    """验证 gen_cases 返回结构。"""

    def test_returns_test_cases_and_summary(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Foo {\n"
            "    public int add(int a, int b) { return a + b; }\n"
            "}",
        )
        analysis = analyzer.analyze(f)
        result = analyzer.gen_cases(analysis)
        assert "test_cases" in result
        assert "summary" in result
        assert len(result["test_cases"]) > 0

    def test_exception_path_generated_when_branches(self, analyzer, tmp_path):
        f = _write_java(
            tmp_path,
            "public class Foo {\n"
            "    public int f(int x) {\n"
            "        if (x > 0) return 1;\n"
            "        return 0;\n"
            "    }\n"
            "}",
        )
        analysis = analyzer.analyze(f)
        result = analyzer.gen_cases(analysis)
        types = {tc["type"] for tc in result["test_cases"]}
        assert "exception_path" in types
