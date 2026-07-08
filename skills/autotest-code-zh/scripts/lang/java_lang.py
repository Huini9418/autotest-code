"""Java 语言适配器：使用 tree-sitter 进行 AST 分析。

tree-sitter-java 独立包，运行时按需 import。
"""

import os

from . import register
from .base import BaseAnalyzer
from .case_design import design_cases

# 类型 -> 边界值映射表（Java 专属）
TYPE_BOUNDARIES: dict[str, list[dict]] = {
    "int": [
        {"value": "0", "category": "zero"},
        {"value": "-1", "category": "negative"},
        {"value": "1", "category": "positive"},
        {"value": "Integer.MAX_VALUE", "category": "max"},
        {"value": "Integer.MIN_VALUE", "category": "min"},
    ],
    "long": [
        {"value": "0L", "category": "zero"},
        {"value": "-1L", "category": "negative"},
        {"value": "1L", "category": "positive"},
        {"value": "Long.MAX_VALUE", "category": "max"},
        {"value": "Long.MIN_VALUE", "category": "min"},
    ],
    "double": [
        {"value": "0.0", "category": "zero"},
        {"value": "-1.0", "category": "negative"},
        {"value": "1.0", "category": "positive"},
        {"value": "Double.MAX_VALUE", "category": "max"},
        {"value": "Double.MIN_VALUE", "category": "min"},
        {"value": "Double.NaN", "category": "nan"},
        {"value": "Double.POSITIVE_INFINITY", "category": "infinity"},
    ],
    "String": [
        {"value": "\"\"", "category": "empty"},
        {"value": "\" \"", "category": "whitespace"},
        {"value": "\"a\"", "category": "single_char"},
        {"value": "\"你好世界\"", "category": "unicode"},
        {"value": "\"a\".repeat(10000)", "category": "very_long"},
        {"value": "\"\\n\\t\\r\"", "category": "special_chars"},
        {"value": "null", "category": "null"},
    ],
    "boolean": [
        {"value": "true", "category": "true"},
        {"value": "false", "category": "false"},
    ],
    "List": [
        {"value": "Collections.emptyList()", "category": "empty"},
        {"value": "List.of(1)", "category": "single"},
        {"value": "List.of(1, 2, 3)", "category": "normal"},
        {"value": "null", "category": "null"},
    ],
    "Map": [
        {"value": "Collections.emptyMap()", "category": "empty"},
        {"value": "Map.of(\"key\", 1)", "category": "single"},
        {"value": "null", "category": "null"},
    ],
    "Object": [
        {"value": "new Object()", "category": "new"},
        {"value": "null", "category": "null"},
    ],
}

# 类型 -> 正常值（等价类划分用）
TYPE_NORMALS: dict[str, list[str]] = {
    "int": ["42", "0"],
    "long": ["42L", "0L"],
    "double": ["3.14", "0.0"],
    "String": ['"hello"', '"test"'],
    "boolean": ["true", "false"],
    "List": ["List.of(1, 2, 3)", "List.of(1)"],
    "Map": ['Map.of("key", 1)'],
    "Object": ["new Object()"],
}


@register("java")
class JavaAnalyzer(BaseAnalyzer):
    """Java 代码分析器，使用 tree-sitter。"""

    def analyze(self, target_path: str) -> dict:
        """AST 分析：提取函数签名、分支、依赖、复杂度。"""
        results: list[dict] = []
        java_files = self._collect_files(target_path)

        for fpath in java_files:
            try:
                source = self._read_source(fpath)
            except OSError:
                continue
            if not source.strip():
                continue
            try:
                tree = self._parse(source)
            except Exception as e:
                results.append(
                    {"file": fpath, "error": f"ParseError: {e}"}
                )
                continue

            if self._has_error(tree.root_node):
                results.append(
                    {"file": fpath, "error": "SyntaxError: parse error detected"}
                )
                continue

            file_info: dict = {
                "file": fpath,
                "functions": [],
                "classes": [],
                "imports": [],
            }
            file_info.update(self._extract_top_level(tree.root_node))
            results.append(file_info)

        summary = self._build_summary(results)
        return {"files": results, "summary": summary}

    def gen_cases(self, analysis: dict) -> dict:
        """基于分析结果生成测试用例清单，委托给共享算法。"""
        return design_cases(analysis, TYPE_BOUNDARIES, TYPE_NORMALS)

    # ------------------------------------------------------------------
    # tree-sitter 解析
    # ------------------------------------------------------------------

    def _parse(self, source: str):
        from tree_sitter import Language, Parser
        import tree_sitter_java as tsjava

        language = Language(tsjava.language())
        parser = Parser(language)
        return parser.parse(source.encode("utf-8"))

    def _has_error(self, node) -> bool:
        if node.type == "ERROR" or node.has_error:
            return True
        return False

    # ------------------------------------------------------------------
    # analyze 辅助方法
    # ------------------------------------------------------------------

    def _collect_files(self, target_path: str) -> list[str]:
        if os.path.isdir(target_path):
            found: list[str] = []
            skip_dirs = {
                "target",
                "build",
                "__pycache__",
                ".git",
                ".venv",
                "venv",
                "node_modules",
            }
            for root, dirs, files in os.walk(target_path):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for name in files:
                    if name.endswith(".java"):
                        found.append(os.path.join(root, name))
            return sorted(found)
        return [target_path] if target_path.endswith(".java") else []

    def _read_source(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _extract_top_level(self, root) -> dict:
        imports: list[str] = []
        functions: list[dict] = []
        classes: list[dict] = []

        for child in root.children:
            ctype = child.type
            if ctype == "package_declaration":
                # package 声明不算 import，跳过
                pass
            elif ctype == "import_declaration":
                imports.append(child.text.decode("utf-8"))
            elif ctype == "class_declaration":
                classes.append(self._analyze_class(child))
            elif ctype == "interface_declaration":
                # 接口暂作为类处理
                classes.append(self._analyze_class(child))
            elif ctype == "enum_declaration":
                classes.append(self._analyze_class(child))
            elif ctype == "method_declaration":
                # 顶层方法（Java 少见但语法允许）
                functions.append(self._analyze_method(child))

        return {
            "imports": imports,
            "functions": functions,
            "classes": classes,
        }

    def _analyze_class(self, node) -> dict:
        """分析 class_declaration / interface_declaration / enum_declaration。"""
        name = ""
        methods: list[dict] = []
        bases: list[str] = []

        for child in node.children:
            if child.type == "identifier":
                name = child.text.decode("utf-8")
            elif child.type == "class_body":
                for member in child.children:
                    if member.type == "method_declaration":
                        finfo = self._analyze_method(member)
                        finfo["qualname"] = f"{name}.{finfo['name']}"
                        methods.append(finfo)
                    elif member.type == "constructor_declaration":
                        finfo = self._analyze_constructor(member)
                        finfo["qualname"] = f"{name}.{finfo['name']}"
                        methods.append(finfo)
            elif child.type == "interface_body":
                for member in child.children:
                    if member.type == "method_declaration":
                        finfo = self._analyze_method(member)
                        finfo["qualname"] = f"{name}.{finfo['name']}"
                        methods.append(finfo)
            elif child.type == "superclass":
                # extends Base
                for sc in child.children:
                    if sc.type in ("type_identifier", "identifier"):
                        bases.append(sc.text.decode("utf-8"))
            elif child.type == "super_interfaces":
                # implements Foo, Bar
                for sc in child.children:
                    if sc.type in ("type_identifier", "identifier"):
                        bases.append(sc.text.decode("utf-8"))
                    elif sc.type == "type_list":
                        for tc in sc.children:
                            if tc.type in ("type_identifier", "identifier"):
                                bases.append(tc.text.decode("utf-8"))

        return {
            "name": name,
            "line": node.start_point[0] + 1,
            "methods": methods,
            "bases": bases,
            "docstring": None,
        }

    def _analyze_method(self, node) -> dict:
        """分析 method_declaration。"""
        name = ""
        return_type = None
        modifiers: list[str] = []
        args: list[dict] = []
        is_static = False

        for child in node.children:
            if child.type == "identifier":
                name = child.text.decode("utf-8")
            elif child.type == "modifiers":
                for mc in child.children:
                    mod_text = mc.text.decode("utf-8")
                    modifiers.append(mod_text)
                    if mod_text == "static":
                        is_static = True
            elif child.type == "formal_parameters":
                args = self._extract_args(child)
            elif child.type in (
                "type_identifier",
                "integral_type",
                "boolean_type",
                "floating_point_type",
                "void_type",
                "generic_type",
                "scoped_type_identifier",
            ):
                return_type = child.text.decode("utf-8")
            elif child.type == "block":
                break

        branches = self._count_branches(node)
        decorators = [f"@{m}" for m in modifiers if m not in (
            "public", "private", "protected", "static", "final",
            "abstract", "synchronized", "native", "transient", "volatile",
        )]

        return {
            "name": name,
            "qualname": name,
            "line": node.start_point[0] + 1,
            "args": args,
            "returns": return_type,
            "decorators": decorators if decorators else [],
            "docstring": None,
            "branches": branches,
            "complexity": 1 + branches,
            "is_async": False,  # Java 无 async 关键字
            "is_static": is_static,
        }

    def _analyze_constructor(self, node) -> dict:
        """分析 constructor_declaration。"""
        name = ""
        modifiers: list[str] = []
        args: list[dict] = []

        for child in node.children:
            if child.type == "identifier":
                name = child.text.decode("utf-8")
            elif child.type == "modifiers":
                for mc in child.children:
                    modifiers.append(mc.text.decode("utf-8"))
            elif child.type == "formal_parameters":
                args = self._extract_args(child)
            elif child.type == "constructor_body":
                break

        branches = self._count_branches(node)

        return {
            "name": name,
            "qualname": name,
            "line": node.start_point[0] + 1,
            "args": args,
            "returns": None,  # 构造函数无返回类型
            "decorators": [],
            "docstring": None,
            "branches": branches,
            "complexity": 1 + branches,
            "is_async": False,
        }

    def _extract_args(self, params_node) -> list[dict]:
        """从 formal_parameters 节点提取参数列表。

        Java 参数: (int a, String b, final double c, int... rest)
        """
        result: list[dict] = []
        for child in params_node.children:
            if child.type in ("(", ")", ","):
                continue
            if child.type == "formal_parameter":
                pname = ""
                ptype = ""
                has_vararg = False
                for fc in child.children:
                    if fc.type == "modifiers":
                        # final 修饰符
                        pass
                    elif fc.type == "identifier":
                        pname = fc.text.decode("utf-8")
                    elif fc.type == "...":
                        has_vararg = True
                    elif fc.type in (
                        "type_identifier",
                        "integral_type",
                        "boolean_type",
                        "floating_point_type",
                        "generic_type",
                        "scoped_type_identifier",
                        "array_type",
                    ):
                        ptype = fc.text.decode("utf-8")
                arg: dict = {
                    "name": pname,
                    "annotation": ptype,
                    "default": None,  # Java 无默认参数
                    "has_default": False,
                }
                if has_vararg:
                    arg["kind"] = "vararg"
                result.append(arg)
            elif child.type == "spread_parameter":
                # int... rest（Java varargs）
                pname = ""
                ptype = ""
                for fc in child.children:
                    if fc.type in (
                        "integral_type",
                        "type_identifier",
                        "boolean_type",
                        "floating_point_type",
                    ):
                        ptype = fc.text.decode("utf-8")
                    elif fc.type == "variable_declarator":
                        for vc in fc.children:
                            if vc.type == "identifier":
                                pname = vc.text.decode("utf-8")
                result.append(
                    {
                        "name": pname,
                        "annotation": ptype,
                        "default": None,
                        "has_default": False,
                        "kind": "vararg",
                    }
                )
        return result

    def _count_branches(self, node) -> int:
        """统计分支节点数，不下钻嵌套类/方法定义。

        计入：if/for/while/do/switch-case/try-catch/ternary/&& ||
        """
        branch_types = {
            "if_statement",
            "for_statement",
            "enhanced_for_statement",
            "while_statement",
            "do_statement",
            "switch_expression",
            "catch_clause",
            "ternary_expression",
        }
        nested_types = {
            "method_declaration",
            "constructor_declaration",
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "lambda_expression",
        }

        count = 0
        for child in self._iter_children(node):
            if child.type in nested_types:
                continue
            if child.type in branch_types:
                count += 1
            elif child.type in ("switch_block_statement_group", "case"):
                count += 1
            elif child.type == "binary_expression":
                for bc in child.children:
                    if bc.type in ("&&", "||"):
                        count += 1
            count += self._count_branches(child)
        return count

    def _iter_children(self, node):
        return node.children

    def _build_summary(self, results: list[dict]) -> dict:
        total_files = len(results)
        error_files = sum(1 for r in results if "error" in r)
        total_funcs = 0
        total_classes = 0
        total_branches = 0
        for r in results:
            if "error" in r:
                continue
            total_funcs += len(r.get("functions", []))
            total_classes += len(r.get("classes", []))
            for fn in r.get("functions", []):
                total_branches += fn.get("branches", 0)
            for cls in r.get("classes", []):
                for m in cls.get("methods", []):
                    total_branches += m.get("branches", 0)
        return {
            "total_files": total_files,
            "error_files": error_files,
            "total_functions": total_funcs,
            "total_classes": total_classes,
            "total_branches": total_branches,
        }
