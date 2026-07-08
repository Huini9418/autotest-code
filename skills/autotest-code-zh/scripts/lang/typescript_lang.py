"""TypeScript 语言适配器：使用 tree-sitter 进行 AST 分析。

tree-sitter-typescript 独立包，运行时按需 import。
与 JavaScript 适配器共享大部分逻辑，额外处理 TypeScript 的：
- 类型注解（type_annotation）
- required_parameter / optional_parameter
- interface_declaration / type_alias_declaration
- export_statement 包裹
- 访问修饰符（accessibility_modifier）
"""

import os

from . import register
from .base import BaseAnalyzer
from .case_design import design_cases

# 类型 -> 边界值映射表（TypeScript 专属，与 JS 相同）
TYPE_BOUNDARIES: dict[str, list[dict]] = {
    "number": [
        {"value": "0", "category": "zero"},
        {"value": "-1", "category": "negative"},
        {"value": "1", "category": "positive"},
        {"value": "Number.MAX_SAFE_INTEGER", "category": "max"},
        {"value": "Number.MIN_SAFE_INTEGER", "category": "min"},
        {"value": "Infinity", "category": "infinity"},
        {"value": "NaN", "category": "nan"},
    ],
    "string": [
        {"value": '""', "category": "empty"},
        {"value": '" "', "category": "whitespace"},
        {"value": '"a"', "category": "single_char"},
        {"value": '"你好世界"', "category": "unicode"},
        {"value": '"a".repeat(10000)', "category": "very_long"},
        {"value": '"<script>alert(1)</script>"', "category": "xss"},
        {"value": '"\\n\\t\\r"', "category": "special_chars"},
    ],
    "boolean": [
        {"value": "true", "category": "true"},
        {"value": "false", "category": "false"},
    ],
    "array": [
        {"value": "[]", "category": "empty"},
        {"value": "[1]", "category": "single"},
        {"value": "[1, 2, 3]", "category": "normal"},
        {"value": "new Array(10000)", "category": "large"},
        {"value": "null", "category": "null"},
    ],
    "object": [
        {"value": "{}", "category": "empty"},
        {"value": "{a: 1}", "category": "single"},
        {"value": "{a: 1, b: 2}", "category": "normal"},
        {"value": "null", "category": "null"},
    ],
    "null": [
        {"value": "null", "category": "null"},
    ],
    "undefined": [
        {"value": "undefined", "category": "undefined"},
    ],
}

# 类型 -> 正常值（等价类划分用）
TYPE_NORMALS: dict[str, list[str]] = {
    "number": ["42", "0"],
    "string": ['"hello"', '"test"'],
    "boolean": ["true", "false"],
    "array": ["[1, 2, 3]", "[1]"],
    "object": ['{key: "value"}'],
    "null": ["null"],
    "undefined": ["undefined"],
}


@register("typescript")
class TypescriptAnalyzer(BaseAnalyzer):
    """TypeScript 代码分析器，使用 tree-sitter。"""

    def analyze(self, target_path: str) -> dict:
        """AST 分析：提取函数签名、分支、依赖、复杂度。"""
        results: list[dict] = []
        ts_files = self._collect_files(target_path)

        for fpath in ts_files:
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
                    {
                        "file": fpath,
                        "error": f"ParseError: {e}",
                    }
                )
                continue

            if self._has_error(tree.root_node):
                results.append(
                    {
                        "file": fpath,
                        "error": "SyntaxError: parse error detected",
                    }
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
        """用 tree-sitter 解析源码，返回 Tree。"""
        from tree_sitter import Language, Parser
        import tree_sitter_typescript as tsts

        language = Language(tsts.language_typescript())
        parser = Parser(language)
        return parser.parse(source.encode("utf-8"))

    def _has_error(self, node) -> bool:
        """递归检查 AST 是否有 ERROR 节点（tree-sitter 错误恢复）。"""
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
                "node_modules",
                "__pycache__",
                ".git",
                ".venv",
                "venv",
                "dist",
                "build",
                ".next",
                ".nuxt",
            }
            for root, dirs, files in os.walk(target_path):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for name in files:
                    if name.endswith(".ts") and not name.endswith(".d.ts"):
                        found.append(os.path.join(root, name))
            return sorted(found)
        return (
            [target_path]
            if target_path.endswith(".ts") and not target_path.endswith(".d.ts")
            else []
        )

    def _read_source(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _extract_top_level(self, root) -> dict:
        imports: list[str] = []
        functions: list[dict] = []
        classes: list[dict] = []

        for child in root.children:
            ctype = child.type
            if ctype == "import_statement":
                imports.append(child.text.decode("utf-8"))
            elif ctype == "function_declaration":
                functions.append(self._analyze_function(child))
            elif ctype == "class_declaration":
                classes.append(self._analyze_class(child))
            elif ctype in (
                "lexical_declaration",
                "variable_declaration",
            ):
                # const f = (x) => x;  或  const f = function(x) {}
                func = self._try_extract_var_function(child)
                if func:
                    functions.append(func)
                else:
                    # const bar = require('bar');
                    imp = self._try_extract_require_from_var(child)
                    if imp:
                        imports.append(imp)
            elif ctype == "export_statement":
                # export function / export class / export const
                extracted = self._extract_from_export(child)
                if extracted:
                    for item in extracted:
                        if "methods" in item:
                            classes.append(item)
                        else:
                            functions.append(item)
            elif ctype == "expression_statement":
                # require('...') 调用
                imp = self._try_extract_require(child)
                if imp:
                    imports.append(imp)

        return {
            "imports": imports,
            "functions": functions,
            "classes": classes,
        }

    def _extract_from_export(self, node) -> list[dict]:
        """从 export_statement 中提取函数或类。"""
        results: list[dict] = []
        for child in node.children:
            if child.type == "function_declaration":
                results.append(self._analyze_function(child))
            elif child.type == "class_declaration":
                results.append(self._analyze_class(child))
            elif child.type in ("lexical_declaration", "variable_declaration"):
                func = self._try_extract_var_function(child)
                if func:
                    results.append(func)
        return results

    def _analyze_function(self, node) -> dict:
        """分析 function_declaration / arrow_function / function_expression。"""
        name = self._get_function_name(node)
        args = self._extract_args(node)
        returns = self._extract_return_type(node)
        branches = self._count_branches(node)
        is_async = self._is_async(node)

        return {
            "name": name,
            "qualname": name,
            "line": node.start_point[0] + 1,
            "args": args,
            "returns": returns,
            "decorators": [],
            "docstring": None,
            "branches": branches,
            "complexity": 1 + branches,
            "is_async": is_async,
        }

    def _analyze_class(self, node) -> dict:
        """分析 class_declaration。"""
        name = ""
        methods: list[dict] = []
        for child in node.children:
            if child.type == "identifier" or child.type == "type_identifier":
                name = child.text.decode("utf-8")
            elif child.type == "class_body":
                for member in child.children:
                    if member.type == "method_definition":
                        finfo = self._analyze_function(member)
                        finfo["qualname"] = f"{name}.{finfo['name']}"
                        methods.append(finfo)
        # 提取继承
        bases: list[str] = []
        for child in node.children:
            if child.type == "class_heritage":
                for hc in child.children:
                    if hc.type == "extends_clause":
                        for ec in hc.children:
                            if ec.type in ("identifier", "type_identifier"):
                                bases.append(ec.text.decode("utf-8"))
                    elif hc.type == "implements_clause":
                        for ic in hc.children:
                            if ic.type in ("identifier", "type_identifier"):
                                bases.append(ic.text.decode("utf-8"))
        return {
            "name": name,
            "line": node.start_point[0] + 1,
            "methods": methods,
            "bases": bases,
            "docstring": None,
        }

    def _get_function_name(self, node) -> str:
        """从函数节点提取函数名。"""
        for child in node.children:
            if child.type in ("identifier", "property_identifier"):
                return child.text.decode("utf-8")
        return "anonymous"

    def _try_extract_var_function(self, node) -> dict | None:
        """从 lexical_declaration / variable_declaration 中提取箭头函数或函数表达式。"""
        for child in node.children:
            if child.type == "variable_declarator":
                var_name = ""
                func_node = None
                for vc in child.children:
                    if vc.type == "identifier" and not var_name:
                        var_name = vc.text.decode("utf-8")
                    elif vc.type in (
                        "arrow_function",
                        "function_expression",
                    ):
                        func_node = vc
                if func_node and var_name:
                    finfo = self._analyze_function(func_node)
                    finfo["name"] = var_name
                    finfo["qualname"] = var_name
                    return finfo
        return None

    def _try_extract_require(self, node) -> str | None:
        """从 expression_statement 中提取 require('...') 调用。"""
        for child in node.children:
            if child.type == "call_expression":
                for cc in child.children:
                    if (
                        cc.type == "identifier"
                        and cc.text.decode("utf-8") == "require"
                    ):
                        return child.text.decode("utf-8")
        return None

    def _try_extract_require_from_var(self, node) -> str | None:
        """从 lexical_declaration 中提取 require('...') 调用。"""
        for child in node.children:
            if child.type == "variable_declarator":
                for vc in child.children:
                    if vc.type == "call_expression":
                        for cc in vc.children:
                            if (
                                cc.type == "identifier"
                                and cc.text.decode("utf-8") == "require"
                            ):
                                return vc.text.decode("utf-8")
        return None

    def _extract_args(self, func_node) -> list[dict]:
        """从函数节点提取参数列表，含类型注解。"""
        result: list[dict] = []
        params_node = None
        for child in func_node.children:
            if child.type == "formal_parameters":
                params_node = child
                break
        if not params_node:
            return result

        for child in params_node.children:
            if child.type in ("(", ")", ","):
                continue
            # TypeScript: required_parameter / optional_parameter
            if child.type in (
                "required_parameter",
                "optional_parameter",
                "rest_pattern",
            ):
                arg = self._extract_ts_param(child)
                if arg:
                    result.append(arg)
            elif child.type == "identifier":
                # 无类型注解的参数（JS 兼容）
                result.append(
                    {
                        "name": child.text.decode("utf-8"),
                        "annotation": None,
                        "default": None,
                        "has_default": False,
                    }
                )
            elif child.type == "assignment_pattern":
                # b = 1（JS 兼容）
                pname = ""
                default_val = None
                for ac in child.children:
                    if ac.type == "identifier" and not pname:
                        pname = ac.text.decode("utf-8")
                    elif ac.type not in ("=",):
                        if default_val is None:
                            default_val = ac.text.decode("utf-8")
                result.append(
                    {
                        "name": pname,
                        "annotation": None,
                        "default": default_val,
                        "has_default": True,
                    }
                )
        return result

    def _extract_ts_param(self, node) -> dict | None:
        """提取 TypeScript 参数节点（required_parameter / optional_parameter）。"""
        pname = ""
        annotation = None
        default_val = None
        has_default = False

        for child in node.children:
            if child.type == "identifier" and not pname:
                pname = child.text.decode("utf-8")
            elif child.type == "rest_pattern":
                # ...rest
                for rc in child.children:
                    if rc.type == "identifier":
                        pname = rc.text.decode("utf-8")
                result = {
                    "name": pname,
                    "annotation": None,
                    "default": None,
                    "has_default": False,
                    "kind": "vararg",
                }
                return result
            elif child.type == "type_annotation":
                annotation = self._extract_type_text(child)
            elif child.type == "=":
                has_default = True
            elif child.type not in (":", "=", "type_annotation"):
                if has_default and default_val is None:
                    default_val = child.text.decode("utf-8")

        return {
            "name": pname,
            "annotation": annotation,
            "default": default_val,
            "has_default": has_default,
        }

    def _extract_type_text(self, type_node) -> str:
        """从 type_annotation 节点提取类型文本。"""
        # type_annotation 节点的第一个子节点是 ':'，第二个是实际类型
        parts: list[str] = []
        for child in type_node.children:
            if child.type != ":":
                parts.append(child.text.decode("utf-8"))
        return "".join(parts).strip()

    def _extract_return_type(self, func_node) -> str | None:
        """从函数节点提取返回类型注解。"""
        found_annotation = False
        for child in func_node.children:
            if child.type == "type_annotation":
                found_annotation = True
                return self._extract_type_text(child)
        return None

    def _count_branches(self, node) -> int:
        """统计分支节点数，不下钻嵌套函数/类定义。

        计入：If/For/While/Try-Catch/Switch-Case/Ternary/&& ||/
        """
        branch_types = {
            "if_statement",
            "for_statement",
            "for_in_statement",
            "while_statement",
            "do_statement",
            "catch_clause",
            "ternary_expression",
        }
        nested_types = {
            "function_declaration",
            "function_expression",
            "arrow_function",
            "class_declaration",
        }

        count = 0
        for child in self._iter_children(node):
            if child.type in nested_types:
                continue
            if child.type in branch_types:
                count += 1
            elif child.type in ("switch_case", "switch_default"):
                count += 1
            elif child.type == "binary_expression":
                for bc in child.children:
                    if bc.type in ("&&", "||"):
                        count += 1
            count += self._count_branches(child)
        return count

    def _iter_children(self, node):
        """安全遍历子节点。"""
        return node.children

    def _is_async(self, node) -> bool:
        """检查函数是否有 async 修饰符。"""
        for child in node.children:
            if child.type == "async":
                return True
        return False

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
