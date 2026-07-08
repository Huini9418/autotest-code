"""Go 语言适配器：使用 tree-sitter 进行 AST 分析。

tree-sitter-go 独立包，运行时按需 import。
"""

import os

from . import register
from .base import BaseAnalyzer
from .case_design import design_cases

# 类型 -> 边界值映射表（Go 专属）
TYPE_BOUNDARIES: dict[str, list[dict]] = {
    "int": [
        {"value": "0", "category": "zero"},
        {"value": "-1", "category": "negative"},
        {"value": "1", "category": "positive"},
        {"value": "math.MaxInt32", "category": "max"},
        {"value": "math.MinInt32", "category": "min"},
    ],
    "int64": [
        {"value": "0", "category": "zero"},
        {"value": "-1", "category": "negative"},
        {"value": "1", "category": "positive"},
        {"value": "math.MaxInt64", "category": "max"},
        {"value": "math.MinInt64", "category": "min"},
    ],
    "float64": [
        {"value": "0.0", "category": "zero"},
        {"value": "-1.0", "category": "negative"},
        {"value": "1.0", "category": "positive"},
        {"value": "math.MaxFloat64", "category": "max"},
        {"value": "math.SmallestNonzeroFloat64", "category": "smallest"},
        {"value": "math.NaN()", "category": "nan"},
        {"value": "math.Inf(1)", "category": "infinity"},
    ],
    "string": [
        {"value": "\"\"", "category": "empty"},
        {"value": "\" \"", "category": "whitespace"},
        {"value": "\"a\"", "category": "single_char"},
        {"value": "\"你好世界\"", "category": "unicode"},
        {"value": "strings.Repeat(\"a\", 10000)", "category": "very_long"},
        {"value": "\"\\n\\t\\r\"", "category": "special_chars"},
    ],
    "bool": [
        {"value": "true", "category": "true"},
        {"value": "false", "category": "false"},
    ],
    "slice": [
        {"value": "nil", "category": "nil"},
        {"value": "[]int{}", "category": "empty"},
        {"value": "[]int{1}", "category": "single"},
        {"value": "[]int{1, 2, 3}", "category": "normal"},
        {"value": "make([]int, 10000)", "category": "large"},
    ],
    "map": [
        {"value": "nil", "category": "nil"},
        {"value": "map[string]int{}", "category": "empty"},
        {"value": "map[string]int{\"a\": 1}", "category": "single"},
    ],
    "error": [
        {"value": "nil", "category": "nil"},
        {"value": "errors.New(\"test\")", "category": "error"},
    ],
}

# 类型 -> 正常值（等价类划分用）
TYPE_NORMALS: dict[str, list[str]] = {
    "int": ["42", "0"],
    "int64": ["42", "0"],
    "float64": ["3.14", "0.0"],
    "string": ['"hello"', '"test"'],
    "bool": ["true", "false"],
    "slice": ["[]int{1, 2, 3}", "[]int{1}"],
    "map": ['map[string]int{"key": 1}'],
    "error": ["nil"],
}


@register("go")
class GoAnalyzer(BaseAnalyzer):
    """Go 代码分析器，使用 tree-sitter。"""

    def analyze(self, target_path: str) -> dict:
        """AST 分析：提取函数签名、分支、依赖、复杂度。"""
        results: list[dict] = []
        go_files = self._collect_files(target_path)

        for fpath in go_files:
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
        import tree_sitter_go as tsgo

        language = Language(tsgo.language())
        parser = Parser(language)
        return parser.parse(source.encode("utf-8"))

    def _has_error(self, node) -> bool:
        """递归检查 AST 是否有 ERROR 或 MISSING 节点。

        tree-sitter-go 的 has_error 属性对 struct 声明可能误报，
        因此只检查实际的 ERROR 节点类型和 MISSING 节点。
        """
        if node.type == "ERROR" or node.is_missing:
            return True
        for child in node.children:
            if self._has_error(child):
                return True
        return False

    # ------------------------------------------------------------------
    # analyze 辅助方法
    # ------------------------------------------------------------------

    def _collect_files(self, target_path: str) -> list[str]:
        if os.path.isdir(target_path):
            found: list[str] = []
            skip_dirs = {
                "vendor",
                "__pycache__",
                ".git",
                ".venv",
                "venv",
                "node_modules",
                "dist",
                "build",
            }
            for root, dirs, files in os.walk(target_path):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for name in files:
                    if name.endswith(".go") and not name.endswith("_test.go"):
                        found.append(os.path.join(root, name))
            return sorted(found)
        return [target_path] if target_path.endswith(".go") else []

    def _read_source(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _extract_top_level(self, root) -> dict:
        imports: list[str] = []
        functions: list[dict] = []
        classes: list[dict] = []

        for child in root.children:
            ctype = child.type
            if ctype == "import_declaration":
                imports.append(child.text.decode("utf-8"))
            elif ctype == "function_declaration":
                functions.append(self._analyze_function(child))
            elif ctype == "method_declaration":
                functions.append(self._analyze_method(child))
            elif ctype == "type_declaration":
                # type Calculator struct { ... }
                cls = self._try_extract_struct(child)
                if cls:
                    classes.append(cls)

        return {
            "imports": imports,
            "functions": functions,
            "classes": classes,
        }

    def _analyze_function(self, node) -> dict:
        """分析 function_declaration。"""
        name = self._get_func_name(node)
        args = self._extract_params(node)
        returns = self._extract_return_types(node)
        branches = self._count_branches(node)

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
            "is_async": False,  # Go 无 async
        }

    def _analyze_method(self, node) -> dict:
        """分析 method_declaration（带 receiver 的方法）。

        func (c *Calculator) GetX() int { ... }
        """
        name = ""
        receiver_type = ""
        # 第一个 parameter_list 是 receiver，第二个是参数
        param_lists = []
        for child in node.children:
            if child.type == "field_identifier":
                name = child.text.decode("utf-8")
            elif child.type == "parameter_list":
                param_lists.append(child)
            elif child.type == "identifier":
                # 可能是 receiver 变量名
                pass

        # receiver 在第一个 parameter_list
        if param_lists:
            receiver_params = self._extract_param_list(param_lists[0])
            if receiver_params:
                receiver_type = receiver_params[0].get("annotation", "")

        # 方法参数在第二个 parameter_list
        args = []
        if len(param_lists) > 1:
            args = self._extract_param_list(param_lists[1])

        returns = self._extract_return_types(node)
        branches = self._count_branches(node)
        qualname = f"{receiver_type}.{name}" if receiver_type else name

        return {
            "name": name,
            "qualname": qualname,
            "line": node.start_point[0] + 1,
            "args": args,
            "returns": returns,
            "decorators": [],
            "docstring": None,
            "branches": branches,
            "complexity": 1 + branches,
            "is_async": False,
        }

    def _try_extract_struct(self, node) -> dict | None:
        """从 type_declaration 中提取 struct。"""
        for child in node.children:
            if child.type == "type_spec":
                name = ""
                fields: list[dict] = []
                for tc in child.children:
                    if tc.type == "type_identifier":
                        name = tc.text.decode("utf-8")
                    elif tc.type == "struct_type":
                        fields = self._extract_struct_fields(tc)
                if name:
                    # struct 的方法通过 method_declaration 单独提取
                    # 这里只记录 struct 本身
                    return {
                        "name": name,
                        "line": node.start_point[0] + 1,
                        "methods": [],
                        "bases": [],
                        "docstring": None,
                    }
        return None

    def _extract_struct_fields(self, struct_node) -> list[dict]:
        """提取 struct 的字段列表。"""
        fields: list[dict] = []
        for child in struct_node.children:
            if child.type == "field_declaration_list":
                for fc in child.children:
                    if fc.type == "field_declaration":
                        fname = ""
                        ftype = ""
                        for fcc in fc.children:
                            if fcc.type == "field_identifier":
                                fname = fcc.text.decode("utf-8")
                            elif fcc.type in (
                                "type_identifier",
                                "pointer_type",
                                "qualified_type",
                                "slice_type",
                                "map_type",
                                "interface_type",
                                "channel_type",
                                "function_type",
                            ):
                                ftype = fcc.text.decode("utf-8")
                        if fname:
                            fields.append({"name": fname, "type": ftype})
        return fields

    def _get_func_name(self, node) -> str:
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf-8")
        return "anonymous"

    def _extract_params(self, func_node) -> list[dict]:
        """从 function_declaration 提取参数列表。"""
        for child in func_node.children:
            if child.type == "parameter_list":
                return self._extract_param_list(child)
        return []

    def _extract_param_list(self, param_list_node) -> list[dict]:
        """从 parameter_list 节点提取参数。

        Go 参数特点：
        - 可以多个参数共享一个类型：func foo(a, b int)
        - 参数名可省略：func foo(int, string) (返回值)
        """
        result: list[dict] = []
        for child in param_list_node.children:
            if child.type in ("(", ")", ",", "comment"):
                continue
            if child.type == "variadic_parameter_declaration":
                # items ...string
                names: list[str] = []
                ptype = ""
                for pc in child.children:
                    if pc.type == "identifier":
                        names.append(pc.text.decode("utf-8"))
                    elif pc.type == "...":
                        pass
                    elif pc.type not in (",",):
                        ptype = pc.text.decode("utf-8")
                for n in names:
                    result.append(
                        {
                            "name": n,
                            "annotation": ptype,
                            "default": None,
                            "has_default": False,
                            "kind": "vararg",
                        }
                    )
            elif child.type == "parameter_declaration":
                # 收集所有 identifier 和类型
                names = []
                ptype = ""
                for pc in child.children:
                    if pc.type == "identifier":
                        names.append(pc.text.decode("utf-8"))
                    elif pc.type not in (",",):
                        if not pc.text.decode("utf-8").strip().isspace():
                            ptype = pc.text.decode("utf-8")

                if names:
                    for n in names:
                        result.append(
                            {
                                "name": n,
                                "annotation": ptype,
                                "default": None,
                                "has_default": False,
                            }
                        )
                elif ptype:
                    # 无名参数（常见于返回值列表）
                    result.append(
                        {
                            "name": "",
                            "annotation": ptype,
                            "default": None,
                            "has_default": False,
                        }
                    )
        return result

    def _extract_return_types(self, func_node) -> str | None:
        """提取返回类型。

        Go 可以有 0、1 或多个返回值。
        单返回值: func foo() int
        多返回值: func foo() (int, error)
        """
        # 找到参数列表后的 type 节点
        param_list_count = 0
        for child in func_node.children:
            if child.type == "parameter_list":
                param_list_count += 1
                if param_list_count == 1:
                    # 第一个 parameter_list 是参数，跳过
                    continue
                # 第二个 parameter_list 是多返回值
                types = []
                for pc in child.children:
                    if pc.type == "parameter_declaration":
                        for pcc in pc.children:
                            if pcc.type in (
                                "type_identifier",
                                "pointer_type",
                                "qualified_type",
                                "interface_type",
                                "primitive_type",
                            ):
                                types.append(pcc.text.decode("utf-8"))
                return ", ".join(types) if types else None
            if param_list_count >= 1:
                if child.type == "type_identifier":
                    return child.text.decode("utf-8")
                elif child.type == "block":
                    break
        return None

    def _count_branches(self, node) -> int:
        """统计分支节点数，不下钻嵌套函数定义。

        计入：if/for/for-in/switch-case/defer-recover
        """
        branch_types = {
            "if_statement",
            "for_statement",
            "expression_switch_statement",
            "type_switch_statement",
            "select_statement",
        }
        nested_types = {
            "function_declaration",
            "method_declaration",
            "func_literal",
        }

        count = 0
        for child in self._iter_children(node):
            if child.type in nested_types:
                continue
            if child.type in branch_types:
                count += 1
            elif child.type in ("expression_case", "default_case"):
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
