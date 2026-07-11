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
        branches_info = self._extract_branches_info(node)
        returns_info = self._extract_returns_info(node)
        is_async = self._is_async(node)

        return {
            "name": name,
            "qualname": name,
            "line": node.start_point[0] + 1,
            "args": args,
            "returns": returns,
            "returns_info": returns_info,
            "decorators": [],
            "docstring": None,
            "branches": branches,
            "branches_info": branches_info,
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

        计入：if/for/while/loop/match/&&/||
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
            elif child.type == "binary_expression":
                # && / || 各算 1 个决策点
                for bc in child.children:
                    if bc.type in ("&&", "||"):
                        count += 1
            count += self._count_branches(child)
        return count

    # ------------------------------------------------------------------
    # branches_info / returns_info 提取（用例设计增强）
    # ------------------------------------------------------------------

    _NESTED_FUNC_TYPES = frozenset({
        "function_item",
        "function_signature_item",
        "closure_expression",
        "struct_item",
        "impl_item",
        "trait_item",
    })

    def _text(self, node) -> str:
        return node.text.decode("utf-8")

    def _extract_branches_info(self, func_node) -> list[dict]:
        """提取分支详细信息。不下钻嵌套函数。"""
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
            if ctype == "if_expression":
                cond = self._extract_if_condition(child)
                out.append({
                    "type": "if",
                    "condition": cond,
                    "line": child.start_point[0] + 1,
                })
            elif ctype in ("for_expression",):
                cond = self._extract_for_condition(child)
                out.append({
                    "type": "for",
                    "condition": cond,
                    "line": child.start_point[0] + 1,
                })
            elif ctype in ("while_expression", "loop_expression"):
                cond = self._extract_while_condition(child)
                out.append({
                    "type": "while",
                    "condition": cond,
                    "line": child.start_point[0] + 1,
                })
            elif ctype == "match_arm":
                pat = self._extract_match_pattern(child)
                out.append({
                    "type": "match_case",
                    "condition": pat,
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
        """Rust 的 if_expression: 'if' <cond> <block> ['else' ...]"""
        after_if = False
        for c in if_node.children:
            if c.type == "if":
                after_if = True
                continue
            if not after_if:
                continue
            if c.type == "block":
                break
            # 第一个非 'if'、非空的表达式就是条件
            return self._text(c)
        return ""

    def _extract_for_condition(self, for_node) -> str:
        """Rust 的 for i in xs { }"""
        parts = []
        after_for = False
        for c in for_node.children:
            if c.type == "for":
                after_for = True
                continue
            if not after_for:
                continue
            if c.type == "block":
                break
            parts.append(self._text(c))
        return " ".join(parts).strip()

    def _extract_while_condition(self, w_node) -> str:
        after_kw = False
        for c in w_node.children:
            if c.type in ("while", "loop"):
                after_kw = True
                continue
            if not after_kw:
                continue
            if c.type == "block":
                break
            return self._text(c)
        return ""

    def _extract_match_pattern(self, arm_node) -> str:
        for c in arm_node.children:
            if c.type == "match_pattern":
                return self._text(c)
        return ""

    def _extract_returns_info(self, func_node) -> list[dict]:
        """提取函数中所有 return 及其守卫条件。

        Rust 特色：
            - 显式 return 语句：`return_expression`
            - 隐式 return：block 最后一个表达式
            - panic! / unimplemented! 视为 raise
            - `return Err(...)` 是错误路径（但仍归为 return）
        """
        out: list[dict] = []
        body = None
        for c in func_node.children:
            if c.type == "block":
                body = c
                break
        if body is None:
            return out

        # 找到 block 中所有非标点子节点
        stmts = [
            c for c in body.children
            if c.type not in ("{", "}")
        ]
        self._collect_returns_from_stmts_with_tail(
            stmts, out, guards=[], depth=0
        )
        return out

    def _collect_returns_from_stmts_with_tail(
        self, stmts, out, guards, depth=0
    ):
        """按顺序处理语句列表：最后一条是 tail (隐式 return)，
        并追踪 early return / early panic 后累积 negation guard。
        """
        implicit: list[str] = []
        for i, stmt in enumerate(stmts):
            is_last = (i == len(stmts) - 1)
            effective_guards = guards + implicit
            self._collect_returns_from_stmt(
                stmt, out, effective_guards, depth, is_tail=is_last
            )
            # 检测 early return / early panic 模式
            cond = self._get_early_return_cond(stmt)
            if cond is not None:
                implicit.append(f"not ({cond})")

    def _get_early_return_cond(self, stmt):
        """如果 stmt 是 `if (cond) { ... 必然 return/panic ... }` 且无 else，
        返回 cond；否则返回 None。
        """
        # Rust 里可能是 expression_statement > if_expression
        if_node = None
        if stmt.type == "expression_statement":
            for c in stmt.children:
                if c.type == "if_expression":
                    if_node = c
                    break
        elif stmt.type == "if_expression":
            if_node = stmt
        if if_node is None:
            return None
        # 检查是否无 else
        has_else = any(
            c.type == "else_clause" for c in if_node.children
        )
        if has_else:
            return None
        # 找 then block
        then_block = None
        for c in if_node.children:
            if c.type == "block":
                then_block = c
                break
        if then_block is None:
            return None
        if not self._block_terminates(then_block):
            return None
        return self._extract_if_condition(if_node)

    def _block_terminates(self, block_node) -> bool:
        """判断 Rust block 是否必然以 return_expression / panic! / unreachable! 结束。"""
        if block_node.type != "block":
            return False
        stmts = [
            c for c in block_node.children
            if c.type not in ("{", "}")
        ]
        if not stmts:
            return False
        last = stmts[-1]
        # 显式 return
        if last.type == "return_expression":
            return True
        # expression_statement 包 return_expression / macro (panic!)
        if last.type == "expression_statement":
            for c in last.children:
                if c.type == "return_expression":
                    return True
                if c.type == "macro_invocation":
                    name = self._extract_macro_name(c)
                    if name in (
                        "panic", "unimplemented",
                        "todo", "unreachable",
                    ):
                        return True
        return False

    def _process_block_as_tail(self, block_node, out, guards, depth):
        """处理 block，最后一个表达式视为隐式 return，同时支持 early return。"""
        if block_node.type != "block":
            self._collect_returns_from_stmt(
                block_node, out, guards, depth, is_tail=True
            )
            return
        stmts = [
            c for c in block_node.children
            if c.type not in ("{", "}")
        ]
        self._collect_returns_from_stmts_with_tail(
            stmts, out, guards, depth
        )

    def _collect_returns_from_stmt(
        self, stmt, out, guards, depth=0, is_tail=False
    ):
        if depth > 200:
            return
        stype = stmt.type
        if stype in self._NESTED_FUNC_TYPES:
            return

        # 显式 return
        if stype == "return_expression":
            value = self._extract_return_value(stmt)
            # 检查是不是 return Err(...)
            kind, exc_type = self._classify_return_value(value)
            entry = {
                "value": value,
                "kind": kind,
                "guard": " and ".join(guards) if guards else "",
                "line": stmt.start_point[0] + 1,
            }
            if exc_type:
                entry["exception_type"] = exc_type
            out.append(entry)
            return

        # expression_statement 包装的 return_expression / panic! / if_expression / match_expression
        if stype == "expression_statement":
            # 判断是否有分号（有则不是 tail）
            has_semicolon = any(c.type == ";" for c in stmt.children)
            effective_tail = is_tail and not has_semicolon
            for c in stmt.children:
                if c.type == "return_expression":
                    self._collect_returns_from_stmt(
                        c, out, guards, depth, is_tail=False
                    )
                    return
                if c.type == "macro_invocation":
                    macro = self._extract_macro_name(c)
                    if macro in ("panic", "unimplemented", "todo", "unreachable"):
                        out.append({
                            "value": self._text(c),
                            "kind": "raise",
                            "exception_type": f"{macro}!",
                            "guard": (
                                " and ".join(guards) if guards else ""
                            ),
                            "line": stmt.start_point[0] + 1,
                        })
                        return
                if c.type == "if_expression":
                    self._collect_returns_from_stmt(
                        c, out, guards, depth, is_tail=effective_tail
                    )
                    return
                if c.type == "match_expression":
                    self._collect_returns_from_stmt(
                        c, out, guards, depth, is_tail=effective_tail
                    )
                    return
                # 其他表达式作为 tail 就是隐式 return
                if effective_tail and c.type not in (";",):
                    value = self._text(c)
                    kind, exc_type = self._classify_return_value(value)
                    entry = {
                        "value": value,
                        "kind": kind,
                        "guard": " and ".join(guards) if guards else "",
                        "line": c.start_point[0] + 1,
                    }
                    if exc_type:
                        entry["exception_type"] = exc_type
                    out.append(entry)
                    return
            return

        # if 表达式作为 tail: 每个分支是隐式 return
        if stype == "if_expression":
            cond = self._extract_if_condition(stmt)
            # 找 then_block 和 else 部分
            then_block = None
            else_part = None
            after_cond = False
            for c in stmt.children:
                if c.type == "if":
                    continue
                if c.type == "block" and then_block is None:
                    then_block = c
                    after_cond = True
                elif c.type == "else_clause":
                    for ec in c.children:
                        if ec.type == "else":
                            continue
                        else_part = ec
                        break
                elif not after_cond:
                    # 这是条件表达式
                    continue

            if then_block is not None:
                # is_tail 决定 then_block 的最后表达式是不是隐式 return
                if is_tail:
                    self._process_block_as_tail(
                        then_block, out, guards + [cond], depth + 1
                    )
                else:
                    self._process_block_no_tail(
                        then_block, out, guards + [cond], depth + 1
                    )
            if else_part is not None:
                neg = f"not ({cond})"
                if else_part.type == "if_expression":
                    self._collect_returns_from_stmt(
                        else_part, out, guards + [neg], depth + 1,
                        is_tail=is_tail
                    )
                elif else_part.type == "block":
                    if is_tail:
                        self._process_block_as_tail(
                            else_part, out, guards + [neg], depth + 1
                        )
                    else:
                        self._process_block_no_tail(
                            else_part, out, guards + [neg], depth + 1
                        )
            return

        # match 表达式作为 tail: 每个 arm 是一个 return
        if stype == "match_expression":
            # match 表达式很复杂，简化处理：只在 tail 时提取 arm 值
            if is_tail:
                self._collect_match_returns(
                    stmt, out, guards, depth
                )
            return

        # 循环体：内部 return 视为无额外守卫
        if stype in (
            "for_expression", "while_expression", "loop_expression"
        ):
            for c in stmt.children:
                if c.type == "block":
                    self._process_block_no_tail(
                        c, out, guards, depth + 1
                    )
            return

        # block 中作为 tail 的裸表达式 = 隐式 return
        if is_tail and stype not in (
            "let_declaration", "expression_statement", "empty_statement"
        ):
            value = self._text(stmt)
            kind, exc_type = self._classify_return_value(value)
            entry = {
                "value": value,
                "kind": kind,
                "guard": " and ".join(guards) if guards else "",
                "line": stmt.start_point[0] + 1,
            }
            if exc_type:
                entry["exception_type"] = exc_type
            out.append(entry)
            return

    def _process_block_no_tail(self, block_node, out, guards, depth):
        """处理 block，最后一个表达式不视为隐式 return。"""
        if block_node.type != "block":
            self._collect_returns_from_stmt(
                block_node, out, guards, depth, is_tail=False
            )
            return
        for c in block_node.children:
            if c.type in ("{", "}"):
                continue
            self._collect_returns_from_stmt(
                c, out, guards, depth, is_tail=False
            )

    def _collect_match_returns(self, match_node, out, guards, depth):
        """处理 match 表达式的所有 arm。"""
        for c in match_node.children:
            if c.type == "match_block":
                for arm in c.children:
                    if arm.type == "match_arm":
                        pat = self._extract_match_pattern(arm)
                        arm_guard = f"match => {pat}"
                        # 找 arm 的 body（可能是表达式或 block）
                        body = None
                        for ac in arm.children:
                            if ac.type not in (
                                "match_pattern", "=>", ",",
                            ):
                                body = ac
                                break
                        if body is None:
                            continue
                        if body.type == "block":
                            self._process_block_as_tail(
                                body, out, guards + [arm_guard], depth + 1
                            )
                        else:
                            # 表达式作为返回值
                            value = self._text(body)
                            kind, exc_type = (
                                self._classify_return_value(value)
                            )
                            entry = {
                                "value": value,
                                "kind": kind,
                                "guard": " and ".join(
                                    guards + [arm_guard]
                                ),
                                "line": body.start_point[0] + 1,
                            }
                            if exc_type:
                                entry["exception_type"] = exc_type
                            out.append(entry)

    def _extract_return_value(self, ret_node) -> str:
        """return_expression: `return <expr>` 或裸 `return`"""
        skip = {"return", ";"}
        for c in ret_node.children:
            if c.type not in skip:
                return self._text(c)
        return "()"

    def _classify_return_value(self, value: str) -> tuple:
        """判断返回值是普通 return 还是错误路径。

        Rust 里 `Err(...)` 是错误路径，但仍属于 return（不是 panic）。
        为了让 case_design 生成更好的 expected，我们把 Err 也标记出来。

        Returns: (kind, exception_type or None)
        """
        stripped = value.strip()
        if stripped.startswith("Err(") or stripped.startswith("Err {"):
            # Rust 的错误值 —— 标为 return 但记录额外信息
            return ("return", None)
        return ("return", None)

    def _extract_macro_name(self, macro_node) -> str:
        """从 macro_invocation 提取宏名。"""
        for c in macro_node.children:
            if c.type == "identifier":
                return self._text(c)
        return ""

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
