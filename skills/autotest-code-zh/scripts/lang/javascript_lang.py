"""JavaScript 语言适配器：使用 tree-sitter 进行 AST 分析。

tree-sitter-javascript 独立包，运行时按需 import。
"""

import os

from . import register
from .base import BaseAnalyzer
from .case_design import design_cases

# 类型 -> 边界值映射表（JavaScript 专属）
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


@register("javascript")
class JavascriptAnalyzer(BaseAnalyzer):
    """JavaScript 代码分析器，使用 tree-sitter。"""

    def analyze(self, target_path: str) -> dict:
        """AST 分析：提取函数签名、分支、依赖、复杂度。"""
        results: list[dict] = []
        js_files = self._collect_files(target_path)

        for fpath in js_files:
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

            # tree-sitter 有错误恢复，检查是否有 ERROR 节点
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
        import tree_sitter_javascript as tsjs

        language = Language(tsjs.language())
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
                    if name.endswith(".js"):
                        found.append(os.path.join(root, name))
            return sorted(found)
        return (
            [target_path] if target_path.endswith(".js") else []
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

    def _analyze_function(self, node) -> dict:
        """分析 function_declaration / arrow_function / function_expression。"""
        name = self._get_function_name(node)
        args = self._extract_args(node)
        branches = self._count_branches(node)
        branches_info = self._extract_branches_info(node)
        returns_info = self._extract_returns_info(node)
        is_async = self._is_async(node)

        return {
            "name": name,
            "qualname": name,
            "line": node.start_point[0] + 1,
            "args": args,
            "returns": None,  # JS 无返回类型注解
            "returns_info": returns_info,
            "decorators": [],
            "docstring": None,
            "branches": branches,
            "branches_info": branches_info,
            "complexity": 1 + branches,
            "is_async": is_async,
        }

    def _analyze_class(self, node) -> dict:
        """分析 class_declaration。"""
        name = ""
        methods: list[dict] = []
        for child in node.children:
            if child.type == "identifier":
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
                    if hc.type == "identifier":
                        bases.append(hc.text.decode("utf-8"))
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
        # arrow_function 在 variable_declarator 中，名字由调用方设置
        return "anonymous"

    def _try_extract_var_function(self, node) -> dict | None:
        """从 lexical_declaration / variable_declaration 中提取箭头函数或函数表达式。

        const f = (x) => x;
        const f = function(x) { return x; };
        """
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
        """从 lexical_declaration 中提取 require('...') 调用。

        const bar = require('bar');
        """
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
        """从函数节点提取参数列表。"""
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
            if child.type == "identifier":
                result.append(
                    {
                        "name": child.text.decode("utf-8"),
                        "annotation": None,
                        "default": None,
                        "has_default": False,
                    }
                )
            elif child.type == "assignment_pattern":
                # b = 1
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
            elif child.type == "rest_pattern":
                # ...rest
                pname = "rest"
                for rc in child.children:
                    if rc.type == "identifier":
                        pname = rc.text.decode("utf-8")
                result.append(
                    {
                        "name": pname,
                        "annotation": None,
                        "default": None,
                        "has_default": False,
                        "kind": "vararg",
                    }
                )
        return result

    def _count_branches(self, node) -> int:
        """统计分支节点数，不下钻嵌套函数/类定义。

        计入：If/For/While/Try-Catch/Switch-Case/Ternary/&& ||/
        使用手动递归实现剪枝。
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
                # 每个 case/default 是一个分支
                count += 1
            elif child.type == "binary_expression":
                # && 或 || 各算 1 个决策点
                for bc in child.children:
                    if bc.type in ("&&", "||"):
                        count += 1
            count += self._count_branches(child)
        return count

    # ------------------------------------------------------------------
    # branches_info / returns_info 提取（用例设计增强）
    # ------------------------------------------------------------------

    _NESTED_FUNC_TYPES = frozenset({
        "function_declaration",
        "function_expression",
        "arrow_function",
        "generator_function",
        "generator_function_declaration",
        "method_definition",
        "class_declaration",
    })

    def _text(self, node) -> str:
        """节点源码文本。"""
        return node.text.decode("utf-8")

    def _condition_from_paren(self, paren_node) -> str:
        """从 parenthesized_expression 中提取内层表达式源码。"""
        for c in paren_node.children:
            if c.type not in ("(", ")"):
                return self._text(c)
        # 兜底：整个 parenthesized_expression 文本，去掉两侧括号
        raw = self._text(paren_node).strip()
        if raw.startswith("(") and raw.endswith(")"):
            return raw[1:-1].strip()
        return raw

    def _extract_branches_info(self, func_node) -> list[dict]:
        """提取分支详细信息（条件表达式、位置）。

        不下钻嵌套函数/类。
        """
        out: list[dict] = []
        self._collect_branches_info(func_node, out, depth=0)
        return out

    def _collect_branches_info(self, node, out, depth=0):
        if depth > 200:
            return
        for child in node.children:
            ctype = child.type
            if ctype in self._NESTED_FUNC_TYPES:
                continue
            if ctype == "if_statement":
                cond = self._extract_if_condition(child)
                out.append({
                    "type": "if",
                    "condition": cond,
                    "line": child.start_point[0] + 1,
                })
            elif ctype in ("for_statement", "for_in_statement"):
                cond = self._extract_for_condition(child)
                out.append({
                    "type": "for",
                    "condition": cond,
                    "line": child.start_point[0] + 1,
                })
            elif ctype in ("while_statement", "do_statement"):
                cond = self._extract_while_condition(child)
                out.append({
                    "type": "while",
                    "condition": cond,
                    "line": child.start_point[0] + 1,
                })
            elif ctype == "catch_clause":
                out.append({
                    "type": "except",
                    "condition": "Error",
                    "exception_type": "Error",
                    "line": child.start_point[0] + 1,
                })
            elif ctype == "ternary_expression":
                cond = self._extract_ternary_condition(child)
                out.append({
                    "type": "ifexp",
                    "condition": cond,
                    "line": child.start_point[0] + 1,
                })
            elif ctype in ("switch_case",):
                # case X: —— 找出 X 表达式
                case_expr = self._extract_switch_case_expr(child)
                out.append({
                    "type": "match_case",
                    "condition": case_expr,
                    "line": child.start_point[0] + 1,
                })
            elif ctype == "switch_default":
                out.append({
                    "type": "match_case",
                    "condition": "default",
                    "line": child.start_point[0] + 1,
                })
            elif ctype == "binary_expression":
                for bc in child.children:
                    if bc.type in ("&&", "||"):
                        out.append({
                            "type": "boolop",
                            "condition": self._text(child),
                            "op": bc.type,
                            "line": child.start_point[0] + 1,
                        })
                        break
            self._collect_branches_info(child, out, depth + 1)

    def _extract_if_condition(self, if_node) -> str:
        for c in if_node.children:
            if c.type == "parenthesized_expression":
                return self._condition_from_paren(c)
        return ""

    def _extract_for_condition(self, for_node) -> str:
        """for (init; cond; update) 提取 cond；for-in/of 提取整体。"""
        raw = self._text(for_node).splitlines()[0]
        # 简单启发：取括号内的内容
        start = raw.find("(")
        end = raw.rfind(")")
        if start >= 0 and end > start:
            return raw[start + 1:end].strip()
        return raw.strip()

    def _extract_while_condition(self, while_node) -> str:
        for c in while_node.children:
            if c.type == "parenthesized_expression":
                return self._condition_from_paren(c)
        return ""

    def _extract_ternary_condition(self, tern_node) -> str:
        # ternary: <cond> ? <a> : <b>，取第一个非标点子节点
        for c in tern_node.children:
            if c.type not in ("?", ":"):
                return self._text(c)
        return ""

    def _extract_switch_case_expr(self, case_node) -> str:
        # switch_case 结构：case <expr>: <body>
        for c in case_node.children:
            if c.type not in ("case", ":"):
                return self._text(c)
        return ""

    def _extract_returns_info(self, func_node) -> list[dict]:
        """提取函数中所有 return / throw 及其守卫条件。

        通过遍历 statement_block 中的语句，累积 if 守卫得到 guard。
        """
        out: list[dict] = []
        # 找到函数体（statement_block）
        body = None
        for c in func_node.children:
            if c.type == "statement_block":
                body = c
                break
        if body is None:
            # arrow_function 可能是 x => x + 1（表达式体，不是 statement_block）
            for c in func_node.children:
                if c.type not in (
                    "async", "=>", "identifier", "formal_parameters",
                    "(", ")", "function",
                ):
                    # 表达式体：整个函数体就是一个 return
                    out.append({
                        "value": self._text(c),
                        "kind": "return",
                        "guard": "",
                        "line": c.start_point[0] + 1,
                    })
                    return out
            return out

        # 从 body 收集 statements
        stmts = [s for s in body.children if s.type not in ("{", "}")]
        self._collect_returns_from_body(stmts, out, guards=[], depth=0)
        return out

    def _collect_returns_from_body(self, stmts, out, guards, depth=0):
        """按顺序处理语句列表，early-return 后累积 negation guard。"""
        implicit: list[str] = []
        for stmt in stmts:
            self._collect_returns_from_stmt(
                stmt, out, guards + implicit, depth
            )
            # 检测 early return: if (cond) <body 必然 return/throw> 且无 else
            if stmt.type == "if_statement":
                if self._is_if_without_else(stmt):
                    if self._if_then_terminates(stmt):
                        cond = self._extract_if_condition(stmt)
                        implicit.append(f"not ({cond})")

    def _is_if_without_else(self, if_node) -> bool:
        """检查 if_statement 是否没有 else 分支。"""
        for c in if_node.children:
            if c.type == "else_clause":
                return False
        return True

    def _if_then_terminates(self, if_node) -> bool:
        """检查 if 的 then 分支是否必然 return/throw。"""
        then_body = self._find_if_then_body(if_node)
        if then_body is None:
            return False
        return self._body_terminates(then_body)

    def _find_if_then_body(self, if_node):
        """找到 if 的 then body（可能是 statement_block 或单条语句）。"""
        after_paren = False
        for c in if_node.children:
            if c.type == "parenthesized_expression":
                after_paren = True
                continue
            if not after_paren:
                continue
            if c.type == "else_clause":
                return None
            return c
        return None

    def _body_terminates(self, body_node) -> bool:
        """判断一个 body 是否必然以 return/throw 结束。"""
        # 单条语句体
        if body_node.type in ("return_statement", "throw_statement"):
            return True
        if body_node.type == "statement_block":
            stmts = [
                s for s in body_node.children
                if s.type not in ("{", "}")
            ]
            if not stmts:
                return False
            last = stmts[-1]
            if last.type in ("return_statement", "throw_statement"):
                return True
            if last.type == "if_statement":
                # if/else 都 terminates 才算
                if self._is_if_without_else(last):
                    return False
                # 检查 then 和 else 都 terminates
                then_body = self._find_if_then_body(last)
                else_body = self._find_else_body(last)
                if then_body and else_body:
                    return (
                        self._body_terminates(then_body)
                        and self._body_terminates(else_body)
                    )
        return False

    def _find_else_body(self, if_node):
        """找到 if 的 else body。"""
        for c in if_node.children:
            if c.type == "else_clause":
                for ec in c.children:
                    if ec.type == "else":
                        continue
                    return ec
        return None

    def _process_if_body(self, node, out, guards, depth):
        """处理 if 的 body：如果是 statement_block 就遍历其子节点；
        否则视为单条语句直接递归。
        """
        if node.type == "statement_block":
            stmts = [
                s for s in node.children if s.type not in ("{", "}")
            ]
            self._collect_returns_from_body(
                stmts, out, guards, depth
            )
        else:
            self._collect_returns_from_stmt(
                node, out, guards, depth
            )

    def _collect_returns_from_stmt(self, stmt, out, guards, depth=0):
        if depth > 200:
            return
        stype = stmt.type
        if stype in self._NESTED_FUNC_TYPES:
            return

        if stype == "return_statement":
            value = self._extract_return_value(stmt)
            out.append({
                "value": value,
                "kind": "return",
                "guard": " and ".join(guards) if guards else "",
                "line": stmt.start_point[0] + 1,
            })
            return
        if stype == "throw_statement":
            value = self._extract_throw_value(stmt)
            exc_type = self._extract_throw_type(stmt)
            out.append({
                "value": value,
                "kind": "raise",
                "exception_type": exc_type,
                "guard": " and ".join(guards) if guards else "",
                "line": stmt.start_point[0] + 1,
            })
            return

        if stype == "if_statement":
            cond = self._extract_if_condition(stmt)
            # 找到 if 的 then / else 部分。tree-sitter-javascript 中：
            # - 有 {} → statement_block
            # - 无 {} → 直接是单个语句（如 return_statement）
            # 结构：if_statement > 'if' > parenthesized_expression > <then_stmt> [> else_clause]
            then_stmt = None
            else_stmt = None  # 可能是 statement_block、if_statement、其他语句
            after_paren = False
            for c in stmt.children:
                if c.type == "parenthesized_expression":
                    after_paren = True
                    continue
                if not after_paren:
                    # 跳过 'if' 关键字
                    continue
                if c.type == "else_clause":
                    # else 的内容：跳过 'else' 关键字后的第一个语句节点
                    for ec in c.children:
                        if ec.type == "else":
                            continue
                        else_stmt = ec
                        break
                    break
                # then 分支：after_paren 之后的第一个非 else 子节点
                if then_stmt is None:
                    then_stmt = c
                    # then 之后可能还会跟 else_clause，继续循环

            if then_stmt is not None:
                self._process_if_body(
                    then_stmt, out, guards + [cond], depth + 1
                )
            if else_stmt is not None:
                neg = f"not ({cond})"
                # else if 分支：整个 if_statement 递归
                if else_stmt.type == "if_statement":
                    self._collect_returns_from_stmt(
                        else_stmt, out, guards + [neg], depth + 1
                    )
                else:
                    self._process_if_body(
                        else_stmt, out, guards + [neg], depth + 1
                    )
            return

        if stype == "try_statement":
            for c in stmt.children:
                if c.type == "statement_block":
                    for s in c.children:
                        if s.type in ("{", "}"):
                            continue
                        self._collect_returns_from_stmt(
                            s, out, guards, depth + 1
                        )
                elif c.type == "catch_clause":
                    for s in c.children:
                        if s.type == "statement_block":
                            for inner in s.children:
                                if inner.type in ("{", "}"):
                                    continue
                                self._collect_returns_from_stmt(
                                    inner, out,
                                    guards + ["except Error"], depth + 1,
                                )
                elif c.type == "finally_clause":
                    for s in c.children:
                        if s.type == "statement_block":
                            for inner in s.children:
                                if inner.type in ("{", "}"):
                                    continue
                                self._collect_returns_from_stmt(
                                    inner, out, guards, depth + 1,
                                )
            return

        if stype in (
            "for_statement", "for_in_statement",
            "while_statement", "do_statement",
        ):
            # 循环体内的 return/throw 视为无额外守卫（保守处理）
            for c in stmt.children:
                if c.type == "statement_block":
                    for s in c.children:
                        if s.type in ("{", "}"):
                            continue
                        self._collect_returns_from_stmt(
                            s, out, guards, depth + 1
                        )
            return

        if stype == "switch_statement":
            for c in stmt.children:
                if c.type == "switch_body":
                    for case in c.children:
                        if case.type in ("switch_case", "switch_default"):
                            case_expr = (
                                self._extract_switch_case_expr(case)
                                if case.type == "switch_case"
                                else "default"
                            )
                            case_guard = f"case {case_expr}"
                            for s in case.children:
                                if s.type in ("case", "default", ":"):
                                    continue
                                if s.type in ("switch_case",):
                                    continue
                                self._collect_returns_from_stmt(
                                    s, out, guards + [case_guard],
                                    depth + 1,
                                )
            return

        if stype == "statement_block":
            for s in stmt.children:
                if s.type in ("{", "}"):
                    continue
                self._collect_returns_from_stmt(
                    s, out, guards, depth + 1
                )
            return
        # 其他语句无 return

    def _extract_return_value(self, ret_node) -> str:
        """return 语句的值。"""
        skip = {"return", ";"}
        for c in ret_node.children:
            if c.type not in skip:
                return self._text(c)
        return "undefined"

    def _extract_throw_value(self, throw_node) -> str:
        skip = {"throw", ";"}
        for c in throw_node.children:
            if c.type not in skip:
                return self._text(c)
        return "Error"

    def _extract_throw_type(self, throw_node) -> str:
        """猜测抛出的异常类型名。"""
        for c in throw_node.children:
            if c.type == "new_expression":
                for nc in c.children:
                    if nc.type == "identifier":
                        return self._text(nc)
            if c.type == "identifier":
                return self._text(c)
            if c.type == "call_expression":
                for cc in c.children:
                    if cc.type == "identifier":
                        return self._text(cc)
        return "Error"

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
