"""Python 语言适配器：使用标准库 ast 模块进行 AST 分析。

从零设计的工程选择：ast 模块零外部依赖、100% 覆盖 Python 语法、
提供 ast.get_docstring / ast.unparse / ast.walk 等丰富工具函数。
"""

import ast
import os
import sys
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
        {"value": "sys.maxsize", "category": "max_int"},
        {"value": "-sys.maxsize - 1", "category": "min_int"},
    ],
    "str": [
        {"value": '""', "category": "empty"},
        {"value": '" "', "category": "whitespace"},
        {"value": '"a"', "category": "single_char"},
        {"value": '"你好世界"', "category": "unicode"},
        {"value": '"a" * 10000', "category": "very_long"},
        {"value": '"<script>alert(1)</script>"', "category": "xss"},
        {"value": '"\\n\\t\\r"', "category": "special_chars"},
        {"value": "'\\0'", "category": "null_byte"},
        {"value": "'\\x00\\x01\\x02'", "category": "binary"},
        {"value": "'OR 1=1 --'", "category": "sql_injection"},
        {"value": "'; DROP TABLE users --'", "category": "sql_injection"},
        {"value": "'UNION SELECT username, password FROM users --'", "category": "sql_injection"},
        {"value": "''; ls -la #'", "category": "command_injection"},
        {"value": "'$(rm -rf /)'", "category": "command_injection"},
        {"value": "'&& cat /etc/passwd'", "category": "command_injection"},
        {"value": "'../../etc/passwd'", "category": "path_traversal"},
        {"value": "'%2e%2e/%2e%2e/etc/passwd'", "category": "path_traversal"},
        {"value": "'http://internal-service:8080/secret'", "category": "ssrf"},
        {"value": "'http://169.254.169.254/latest/meta-data/'", "category": "ssrf"},
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
        branches_info = self._extract_branches_info(node)
        returns_info = self._extract_returns_info(node)
        decorators = self._extract_decorators(node)
        returns = ast.unparse(node.returns) if node.returns else None
        doc = ast.get_docstring(node)

        return {
            "name": node.name,
            "qualname": node.name,
            "line": node.lineno,
            "args": args,
            "returns": returns,
            "returns_info": returns_info,
            "decorators": decorators,
            "docstring": doc,
            "branches": branches,
            "branches_info": branches_info,
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

    def _extract_branches_info(self, node: ast.AST) -> list[dict]:
        """提取分支详细信息（条件表达式、位置、异常类型）。

        与 _count_branches 不同，此方法保留具体的分支语义，供用例设计使用。
        不下钻嵌套函数/类。

        Returns:
            分支信息列表，每项含:
                - type: "if" / "for" / "while" / "except" / "match_case" /
                        "boolop" / "ifexp"
                - condition: 条件表达式源码（str）
                - line: 起始行号
                - exception_type: except 分支专用，异常类型名（str | None）
        """
        branches: list[dict] = []
        self._collect_branches_info(node, branches)
        return branches

    def _collect_branches_info(
        self, node: ast.AST, out: list[dict], depth: int = 0
    ) -> None:
        """递归采集分支信息，遇到嵌套函数/类时停止下钻。"""
        nested_types = (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
        )
        # 防止病理性深度递归
        if depth > 200:
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(child, nested_types):
                continue
            if isinstance(child, ast.If):
                out.append({
                    "type": "if",
                    "condition": ast.unparse(child.test),
                    "line": child.lineno,
                })
            elif isinstance(child, ast.For):
                target = ast.unparse(child.target)
                iter_expr = ast.unparse(child.iter)
                out.append({
                    "type": "for",
                    "condition": f"{target} in {iter_expr}",
                    "line": child.lineno,
                })
            elif isinstance(child, ast.While):
                out.append({
                    "type": "while",
                    "condition": ast.unparse(child.test),
                    "line": child.lineno,
                })
            elif isinstance(child, ast.ExceptHandler):
                exc_type = (
                    ast.unparse(child.type) if child.type else "Exception"
                )
                out.append({
                    "type": "except",
                    "condition": exc_type,
                    "exception_type": exc_type,
                    "line": child.lineno,
                })
            elif isinstance(child, ast.IfExp):
                out.append({
                    "type": "ifexp",
                    "condition": ast.unparse(child.test),
                    "line": getattr(child, "lineno", 0),
                })
            elif isinstance(child, ast.Match):
                for case in child.cases:
                    try:
                        pattern_src = ast.unparse(case.pattern)
                    except Exception:
                        pattern_src = "?"
                    out.append({
                        "type": "match_case",
                        "condition": pattern_src,
                        "line": case.pattern.lineno if hasattr(
                            case.pattern, "lineno"
                        ) else child.lineno,
                    })
            elif isinstance(child, ast.BoolOp):
                op = "and" if isinstance(child.op, ast.And) else "or"
                out.append({
                    "type": "boolop",
                    "condition": ast.unparse(child),
                    "op": op,
                    "line": getattr(child, "lineno", 0),
                })
            self._collect_branches_info(child, out, depth + 1)

    def _extract_returns_info(
        self, func_node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> list[dict]:
        """提取函数中所有 return / raise 语句及其守卫条件。

        守卫条件 (guard) 是到达该 return 语句所需的路径条件，通过
        追溯 AST 父链累积 if/else 分支得到。不下钻嵌套函数/类。

        Returns:
            列表，每项含:
                - value: return 表达式的源码（raise 时为异常构造源码）
                - kind: "return" | "raise"
                - guard: 到达该语句的条件表达式（"" 表示无条件返回）
                - line: 行号
                - exception_type: 仅 raise 时提供，异常类型名
        """
        out: list[dict] = []
        # 从函数体开始遍历，guards 从空开始
        self._collect_returns_from_body(
            func_node.body, out, guards=[], depth=0
        )
        return out

    def _collect_returns_from_body(
        self,
        stmts: list,
        out: list[dict],
        guards: list[str],
        depth: int = 0,
    ) -> None:
        """按顺序遍历语句列表，处理 early return 的 negation 传播。

        当一个 `if <cond>: <body>` 的 body 里必然 return/raise 时，
        后续所有语句都隐含了 `not (cond)` 这个额外守卫条件。
        这里累积这些隐含条件，让 fall-through 的 return 拿到正确的 guard。
        """
        implicit_guards: list[str] = []
        for stmt in stmts:
            effective_guards = guards + implicit_guards
            self._collect_returns_from_stmt(
                stmt, out, effective_guards, depth
            )
            # 检测 early return 模式：if <cond>: <body 必然 return>
            # 但没有 else 分支
            if isinstance(stmt, ast.If) and not stmt.orelse:
                if self._body_always_terminates(stmt.body):
                    cond_src = ast.unparse(stmt.test)
                    implicit_guards.append(f"not ({cond_src})")

    def _body_always_terminates(self, stmts: list) -> bool:
        """判断一组语句是否必然以 return/raise/panic 结束。

        用于识别 early return / early raise 模式。
        保守判断：只识别 body 里最后一条是 Return/Raise 的简单情形，
        或最后一条是 If 且 then/else 都必然 terminates。
        """
        if not stmts:
            return False
        last = stmts[-1]
        if isinstance(last, (ast.Return, ast.Raise)):
            return True
        # if X: return ... else: return ...  也算 terminates
        if isinstance(last, ast.If):
            if (
                last.orelse
                and self._body_always_terminates(last.body)
                and self._body_always_terminates(last.orelse)
            ):
                return True
        return False

    def _collect_returns_from_stmt(
        self,
        stmt: ast.AST,
        out: list[dict],
        guards: list[str],
        depth: int = 0,
    ) -> None:
        """处理一条语句，累积路径守卫条件。"""
        nested_types = (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
        )
        if depth > 200:
            return
        if isinstance(stmt, nested_types):
            return

        # 直接命中 return / raise
        if isinstance(stmt, ast.Return):
            value_src = (
                ast.unparse(stmt.value) if stmt.value else "None"
            )
            out.append({
                "value": value_src,
                "kind": "return",
                "guard": " and ".join(guards) if guards else "",
                "line": stmt.lineno,
            })
            return
        if isinstance(stmt, ast.Raise):
            if stmt.exc is not None:
                exc_src = ast.unparse(stmt.exc)
                if isinstance(stmt.exc, ast.Call):
                    exc_type = ast.unparse(stmt.exc.func)
                else:
                    exc_type = exc_src
            else:
                exc_src = "raise"
                exc_type = "Exception"
            out.append({
                "value": exc_src,
                "kind": "raise",
                "exception_type": exc_type,
                "guard": " and ".join(guards) if guards else "",
                "line": stmt.lineno,
            })
            return

        # if / elif / else：累积正/反向条件
        if isinstance(stmt, ast.If):
            cond_src = ast.unparse(stmt.test)
            self._collect_returns_from_body(
                stmt.body, out, guards + [cond_src], depth + 1
            )
            if stmt.orelse:
                neg = f"not ({cond_src})"
                self._collect_returns_from_body(
                    stmt.orelse, out, guards + [neg], depth + 1
                )
            return

        # try / except / else / finally
        if isinstance(stmt, ast.Try):
            self._collect_returns_from_body(
                stmt.body, out, guards, depth + 1
            )
            for handler in stmt.handlers:
                exc_type = (
                    ast.unparse(handler.type)
                    if handler.type else "Exception"
                )
                guard_add = f"except {exc_type}"
                self._collect_returns_from_body(
                    handler.body, out, guards + [guard_add], depth + 1
                )
            self._collect_returns_from_body(
                stmt.orelse, out, guards, depth + 1
            )
            self._collect_returns_from_body(
                stmt.finalbody, out, guards, depth + 1
            )
            return

        # for / while / with：body 是顺序执行的语句
        if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
            self._collect_returns_from_body(
                stmt.body, out, guards, depth + 1
            )
            self._collect_returns_from_body(
                stmt.orelse, out, guards, depth + 1
            )
            return
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            self._collect_returns_from_body(
                stmt.body, out, guards, depth + 1
            )
            return

        # match / case
        if isinstance(stmt, ast.Match):
            subject = ast.unparse(stmt.subject)
            for case in stmt.cases:
                try:
                    pat_src = ast.unparse(case.pattern)
                except Exception:
                    pat_src = "?"
                case_guard = f"match {subject} case {pat_src}"
                self._collect_returns_from_body(
                    case.body, out, guards + [case_guard], depth + 1,
                )
            return

        # 其他语句：无法产生 return（表达式语句、赋值等），忽略

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
