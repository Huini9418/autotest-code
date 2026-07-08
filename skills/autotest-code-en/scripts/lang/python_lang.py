"""Python 语言适配器：使用标准库 ast 模块进行 AST 分析。

从零设计的工程选择：ast 模块零外部依赖、100% 覆盖 Python 语法、
提供 ast.get_docstring / ast.unparse / ast.walk 等丰富工具函数。
"""

import ast
import os
from typing import Any

from . import register
from .base import BaseAnalyzer
from .case_design import design_cases

# 类型 -> 边界值映射表（Python 专属）
TYPE_BOUNDARIES: dict[str, list[dict]] = {
    "int": [
        {"value": "0", "category": "zero"},
        {"value": "-1", "category": "negative"},
        {"value": "1", "category": "positive"},
        {"value": "999999999", "category": "large"},
        {"value": "-999999999", "category": "large_negative"},
    ],
    "str": [
        {"value": '""', "category": "empty"},
        {"value": '" "', "category": "whitespace"},
        {"value": '"a"', "category": "single_char"},
        {"value": '"你好世界"', "category": "unicode"},
        {"value": '"a" * 10000', "category": "very_long"},
        {"value": '"<script>alert(1)</script>"', "category": "xss"},
        {"value": '"\\n\\t\\r"', "category": "special_chars"},
    ],
    "float": [
        {"value": "0.0", "category": "zero"},
        {"value": "-1.5", "category": "negative"},
        {"value": "1.5", "category": "positive"},
        {"value": "1e-10", "category": "tiny"},
        {"value": "1e10", "category": "huge"},
        {"value": "float('inf')", "category": "infinity"},
        {"value": "float('nan')", "category": "nan"},
    ],
    "bool": [
        {"value": "True", "category": "true"},
        {"value": "False", "category": "false"},
    ],
    "list": [
        {"value": "[]", "category": "empty"},
        {"value": "[1]", "category": "single"},
        {"value": "[1, 2, 3]", "category": "normal"},
        {"value": "[0] * 10000", "category": "large"},
        {"value": "None", "category": "none"},
    ],
    "dict": [
        {"value": "{}", "category": "empty"},
        {"value": '{"a": 1}', "category": "single"},
        {"value": '{"a": 1, "b": 2}', "category": "normal"},
        {"value": "None", "category": "none"},
    ],
    "None": [
        {"value": "None", "category": "none"},
    ],
}

# 类型 -> 正常值（等价类划分用）
TYPE_NORMALS: dict[str, list[str]] = {
    "int": ["42", "0"],
    "str": ['"hello"', '"test"'],
    "float": ["3.14", "1.0"],
    "bool": ["True", "False"],
    "list": ["[1, 2, 3]", "[1]"],
    "dict": ['{"key": "value"}'],
    "None": ["None"],
}


@register("python")
class PythonAnalyzer(BaseAnalyzer):
    """Python 代码分析器，使用 ast 模块。"""

    def analyze(self, target_path: str) -> dict:
        """AST 分析：提取函数签名、分支、依赖、复杂度。"""
        results: list[dict] = []
        py_files = self._collect_files(target_path)

        for fpath in py_files:
            try:
                source = self._read_source(fpath)
            except OSError:
                continue
            if not source.strip():
                continue
            try:
                tree = ast.parse(source, filename=fpath)
            except SyntaxError as e:
                results.append(
                    {
                        "file": fpath,
                        "error": (
                            f"SyntaxError: {e.msg} (line {e.lineno})"
                        ),
                    }
                )
                continue

            file_info: dict[str, Any] = {
                "file": fpath,
                "functions": [],
                "classes": [],
                "imports": [],
            }
            file_info.update(self._extract_top_level(tree))
            results.append(file_info)

        summary = self._build_summary(results)
        return {"files": results, "summary": summary}

    def gen_cases(self, analysis: dict) -> dict:
        """基于分析结果生成测试用例清单，委托给共享算法。"""
        return design_cases(analysis, TYPE_BOUNDARIES, TYPE_NORMALS)

    # ------------------------------------------------------------------
    # analyze 辅助方法
    # ------------------------------------------------------------------

    def _collect_files(self, target_path: str) -> list[str]:
        if os.path.isdir(target_path):
            found: list[str] = []
            skip_dirs = {
                "__pycache__",
                ".git",
                ".venv",
                "venv",
                "env",
                "node_modules",
                ".mypy_cache",
                ".pytest_cache",
            }
            for root, dirs, files in os.walk(target_path):
                # 原地修改 dirs 阻止 os.walk 下钻被跳过的目录
                dirs[:] = [
                    d for d in dirs if d not in skip_dirs
                ]
                for name in files:
                    if name.endswith(".py"):
                        found.append(os.path.join(root, name))
            return sorted(found)
        return (
            [target_path] if target_path.endswith(".py") else []
        )

    def _read_source(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _extract_top_level(self, tree: ast.Module) -> dict:
        imports: list[str] = []
        functions: list[dict] = []
        classes: list[dict] = []

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(self._format_import(node))
            elif isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                functions.append(self._analyze_function(node))
            elif isinstance(node, ast.ClassDef):
                classes.append(self._analyze_class(node))

        return {
            "imports": imports,
            "functions": functions,
            "classes": classes,
        }

    def _format_import(self, node: ast.AST) -> str:
        if isinstance(node, ast.Import):
            names = ", ".join(a.name for a in node.names)
            return f"import {names}"
        # 处理相对导入的 level（点号数）
        level = "." * getattr(node, "level", 0)
        mod = (node.module or "")
        names = ", ".join(a.name for a in node.names)
        return f"from {level}{mod} import {names}"

    def _analyze_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> dict:
        args = self._extract_args(node)
        branches = self._count_branches(node)
        decorators = self._extract_decorators(node)
        returns = ast.unparse(node.returns) if node.returns else None
        doc = ast.get_docstring(node)

        return {
            "name": node.name,
            "qualname": node.name,
            "line": node.lineno,
            "args": args,
            "returns": returns,
            "decorators": decorators,
            "docstring": doc,
            "branches": branches,
            "complexity": self._cyclomatic_complexity(node),
            "is_async": isinstance(node, ast.AsyncFunctionDef),
        }

    def _analyze_class(self, node: ast.ClassDef) -> dict:
        methods = []
        for item in node.body:
            if isinstance(
                item, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                finfo = self._analyze_function(item)
                finfo["qualname"] = f"{node.name}.{item.name}"
                methods.append(finfo)
        bases = [ast.unparse(b) for b in node.bases]
        return {
            "name": node.name,
            "line": node.lineno,
            "methods": methods,
            "bases": bases,
            "docstring": ast.get_docstring(node),
        }

    def _extract_args(self, node: ast.FunctionDef) -> list[dict]:
        result: list[dict] = []
        defaults_offset = len(node.args.defaults)
        all_args = (
            node.args.posonlyargs + node.args.args
            if hasattr(node.args, "posonlyargs")
            else node.args.args
        )
        total = len(all_args)
        for i, arg in enumerate(all_args):
            has_default = i >= total - defaults_offset
            default_val = None
            if has_default:
                idx = i - (total - defaults_offset)
                default_val = ast.unparse(node.args.defaults[idx])
            annotation = (
                ast.unparse(arg.annotation) if arg.annotation else None
            )
            result.append(
                {
                    "name": arg.arg,
                    "annotation": annotation,
                    "default": default_val,
                    "has_default": has_default,
                }
            )
        if node.args.vararg:
            result.append(
                {
                    "name": node.args.vararg.arg,
                    "annotation": (
                        ast.unparse(node.args.vararg.annotation)
                        if node.args.vararg.annotation
                        else None
                    ),
                    "default": None,
                    "has_default": False,
                    "kind": "vararg",
                }
            )
        # keyword-only args（*args 之后或裸 * 之后）
        kw_defaults = node.args.kw_defaults
        for i, arg in enumerate(node.args.kwonlyargs):
            default_val = None
            has_default = False
            if kw_defaults[i] is not None:
                has_default = True
                default_val = ast.unparse(kw_defaults[i])
            annotation = (
                ast.unparse(arg.annotation) if arg.annotation else None
            )
            result.append(
                {
                    "name": arg.arg,
                    "annotation": annotation,
                    "default": default_val,
                    "has_default": has_default,
                    "kind": "kwonly",
                }
            )
        if node.args.kwarg:
            result.append(
                {
                    "name": node.args.kwarg.arg,
                    "annotation": (
                        ast.unparse(node.args.kwarg.annotation)
                        if node.args.kwarg.annotation
                        else None
                    ),
                    "default": None,
                    "has_default": False,
                    "kind": "kwarg",
                }
            )
        return result

    def _count_branches(self, node: ast.AST) -> int:
        """统计分支节点数，不下钻嵌套函数/类定义。

        计入：If/For/While/ExceptHandler/BoolOp/IfExp/Match
        BoolOp 按 operands-1 计数（标准 McCabe 复杂度）。
        Match 按 case 数计数。
        使用手动递归实现剪枝（ast.walk 无法跳过子树）。
        """
        return self._count_branches_recursive(node)

    def _count_branches_recursive(
        self, node: ast.AST, depth: int = 0
    ) -> int:
        """手动递归统计分支，遇到嵌套函数/类时停止下钻。"""
        count = 0
        nested_types = (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
        )
        for child in ast.iter_child_nodes(node):
            # 任何深度的嵌套函数/类都不下钻（它们会单独分析）
            if isinstance(child, nested_types):
                continue
            if isinstance(child, ast.If):
                count += 1
            elif isinstance(child, ast.For):
                count += 1
            elif isinstance(child, ast.While):
                count += 1
            elif isinstance(child, ast.ExceptHandler):
                count += 1
            elif isinstance(child, ast.BoolOp):
                # BoolOp: a and b and c → 2 个决策点
                count += len(child.values) - 1
            elif isinstance(child, ast.IfExp):
                # 三元表达式 x if cond else y
                count += 1
            elif isinstance(child, ast.Match):
                # match 语句：每个 case 是一个分支
                count += len(child.cases)
            count += self._count_branches_recursive(
                child, depth + 1
            )
        return count

    def _cyclomatic_complexity(self, node: ast.AST) -> int:
        return 1 + self._count_branches(node)

    def _extract_decorators(
        self, node: ast.FunctionDef
    ) -> list[str]:
        return [ast.unparse(d) for d in node.decorator_list]

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
