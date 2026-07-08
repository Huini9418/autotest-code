"""Rust 语言适配器：使用 tree-sitter 进行 AST 分析。

tree-sitter-rust 独立包，运行时按需 import。
"""

import os

from . import register
from .base import BaseAnalyzer
from .case_design import design_cases

# 类型 -> 边界值映射表（Rust 专属）
TYPE_BOUNDARIES: dict[str, list[dict]] = {
    "i32": [
        {"value": "0", "category": "zero"},
        {"value": "-1", "category": "negative"},
        {"value": "1", "category": "positive"},
        {"value": "i32::MAX", "category": "max"},
        {"value": "i32::MIN", "category": "min"},
    ],
    "i64": [
        {"value": "0", "category": "zero"},
        {"value": "-1", "category": "negative"},
        {"value": "1", "category": "positive"},
        {"value": "i64::MAX", "category": "max"},
        {"value": "i64::MIN", "category": "min"},
    ],
    "u32": [
        {"value": "0", "category": "zero"},
        {"value": "1", "category": "positive"},
        {"value": "u32::MAX", "category": "max"},
    ],
    "f64": [
        {"value": "0.0", "category": "zero"},
        {"value": "-1.0", "category": "negative"},
        {"value": "1.0", "category": "positive"},
        {"value": "f64::MAX", "category": "max"},
        {"value": "f64::MIN", "category": "min"},
        {"value": "f64::NAN", "category": "nan"},
        {"value": "f64::INFINITY", "category": "infinity"},
    ],
    "String": [
        {"value": 'String::new()', "category": "empty"},
        {"value": 'String::from(" ")', "category": "whitespace"},
        {"value": 'String::from("a")', "category": "single_char"},
        {"value": 'String::from("你好世界")', "category": "unicode"},
        {"value": 'String::from_utf8(vec![b\'a\'; 10000]).unwrap()', "category": "very_long"},
        {"value": 'String::from("\\n\\t\\r")', "category": "special_chars"},
    ],
    "&str": [
        {"value": '""', "category": "empty"},
        {"value": '" "', "category": "whitespace"},
        {"value": '"a"', "category": "single_char"},
        {"value": '"你好世界"', "category": "unicode"},
        {"value": '"\\n\\t\\r"', "category": "special_chars"},
    ],
    "bool": [
        {"value": "true", "category": "true"},
        {"value": "false", "category": "false"},
    ],
    "Vec": [
        {"value": "Vec::new()", "category": "empty"},
        {"value": "vec![1]", "category": "single"},
        {"value": "vec![1, 2, 3]", "category": "normal"},
        {"value": "vec![0; 10000]", "category": "large"},
    ],
    "Option": [
        {"value": "None", "category": "none"},
        {"value": "Some(42)", "category": "some"},
    ],
    "Result": [
        {"value": "Ok(42)", "category": "ok"},
        {"value": 'Err("test")', "category": "err"},
    ],
}

# 类型 -> 正常值（等价类划分用）
TYPE_NORMALS: dict[str, list[str]] = {
    "i32": ["42", "0"],
    "i64": ["42", "0"],
    "u32": ["42", "0"],
    "f64": ["3.14", "0.0"],
    "String": ['String::from("hello")', 'String::from("test")'],
    "&str": ['"hello"', '"test"'],
    "bool": ["true", "false"],
    "Vec": ["vec![1, 2, 3]", "vec![1]"],
    "Option": ["Some(42)", "None"],
    "Result": ["Ok(42)", 'Err("test")'],
}


@register("rust")
class RustAnalyzer(BaseAnalyzer):
    """Rust 代码分析器，使用 tree-sitter。"""

    def analyze(self, target_path: str) -> dict:
        """AST 分析：提取函数签名、分支、依赖、复杂度。"""
        results: list[dict] = []
        rs_files = self._collect_files(target_path)

        for fpath in rs_files:
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
        import tree_sitter_rust as tsrust

        language = Language(tsrust.language())
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
                "__pycache__",
                ".git",
                ".venv",
                "venv",
                "node_modules",
            }
            for root, dirs, files in os.walk(target_path):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for name in files:
                    if name.endswith(".rs"):
                        found.append(os.path.join(root, name))
            return sorted(found)
        return [target_path] if target_path.endswith(".rs") else []

    def _read_source(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _extract_top_level(self, root) -> dict:
        imports: list[str] = []
        functions: list[dict] = []
        classes: list[dict] = []

        for child in root.children:
            ctype = child.type
            if ctype == "use_declaration":
                imports.append(child.text.decode("utf-8"))
            elif ctype == "function_item":
                functions.append(self._analyze_function(child))
            elif ctype == "struct_item":
                classes.append(self._analyze_struct(child))
            elif ctype == "impl_item":
                # impl 块内的方法提取为独立函数
                impl_funcs = self._extract_impl_methods(child)
                functions.extend(impl_funcs)
            elif ctype == "trait_item":
                # trait 中的方法签名暂不提取为函数
                pass

        return {
            "imports": imports,
            "functions": functions,
            "classes": classes,
        }

    def _analyze_function(self, node) -> dict:
        """分析 function_item。"""
        name = self._get_func_name(node)
        args = self._extract_params(node)
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

    def _analyze_struct(self, node) -> dict:
        """分析 struct_item。"""
        name = ""
        for child in node.children:
            if child.type == "type_identifier":
                name = child.text.decode("utf-8")
                break
        return {
            "name": name,
            "line": node.start_point[0] + 1,
            "methods": [],
            "bases": [],
            "docstring": None,
        }

    def _extract_impl_methods(self, impl_node) -> list[dict]:
        """从 impl 块中提取方法列表。"""
        methods: list[dict] = []
        impl_type = ""
        # 获取 impl 的类型名
        for child in impl_node.children:
            if child.type == "type_identifier":
                impl_type = child.text.decode("utf-8")
                break

        for child in impl_node.children:
            if child.type == "declaration_list":
                for dc in child.children:
                    if dc.type == "function_item":
                        finfo = self._analyze_function(dc)
                        finfo["qualname"] = f"{impl_type}::{finfo['name']}"
                        methods.append(finfo)
        return methods

    def _get_func_name(self, node) -> str:
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf-8")
        return "anonymous"

    def _extract_params(self, func_node) -> list[dict]:
        """从 function_item 提取参数列表。

        Rust 参数: (a: i32, b: &str, c: &mut Vec<i32>)
        self 参数: (&self) 或 (&mut self) 或 (self)
        """
        result: list[dict] = []
        for child in func_node.children:
            if child.type == "parameters":
                for pc in child.children:
                    if pc.type in ("(", ")", ","):
                        continue
                    if pc.type == "parameter":
                        pname = ""
                        ptype = ""
                        has_ref = False
                        for pcc in pc.children:
                            if pcc.type == "identifier":
                                pname = pcc.text.decode("utf-8")
                            elif pcc.type == ":":
                                pass
                            elif pcc.type == "&":
                                has_ref = True
                            elif pcc.type == "mut":
                                pass
                            else:
                                # 类型节点
                                ptype = pcc.text.decode("utf-8")
                        result.append(
                            {
                                "name": pname,
                                "annotation": ptype,
                                "default": None,
                                "has_default": False,
                            }
                        )
                    elif pc.type == "self_parameter":
                        # &self / &mut self / self
                        result.append(
                            {
                                "name": "self",
                                "annotation": pc.text.decode("utf-8"),
                                "default": None,
                                "has_default": False,
                            }
                        )
        return result

    def _extract_return_type(self, func_node) -> str | None:
        """提取返回类型（-> 后的类型）。"""
        found_arrow = False
        for child in func_node.children:
            if child.type == "->":
                found_arrow = True
                continue
            if found_arrow:
                if child.type == "block":
                    break
                # 返回类型节点
                return child.text.decode("utf-8")
        return None

    def _count_branches(self, node) -> int:
        """统计分支节点数，不下钻嵌套函数定义。

        计入：if/for/while/loop/match/try
        """
        branch_types = {
            "if_expression",
            "for_expression",
            "while_expression",
            "loop_expression",
            "match_expression",
        }
        nested_types = {
            "function_item",
            "function_signature_item",
            "struct_item",
            "impl_item",
            "trait_item",
        }

        count = 0
        for child in self._iter_children(node):
            if child.type in nested_types:
                continue
            if child.type in branch_types:
                count += 1
            elif child.type == "match_arm":
                count += 1
            count += self._count_branches(child)
        return count

    def _iter_children(self, node):
        return node.children

    def _is_async(self, node) -> bool:
        for child in node.children:
            if child.type == "async":
                return True
            if child.type == "function_modifiers":
                for mc in child.children:
                    if mc.type == "async":
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
