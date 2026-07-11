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
    # Go 的 nil 字面量（供 _resolve_lang_none 使用）
    "nil": ["nil"],
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
        branches_info = self._extract_branches_info(node)
        returns_info = self._extract_returns_info(node)

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
        branches_info = self._extract_branches_info(node)
        returns_info = self._extract_returns_info(node)
        qualname = f"{receiver_type}.{name}" if receiver_type else name

        return {
            "name": name,
            "qualname": qualname,
            "line": node.start_point[0] + 1,
            "args": args,
            "returns": returns,
            "returns_info": returns_info,
            "decorators": [],
            "docstring": None,
            "branches": branches,
            "branches_info": branches_info,
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

        计入：if/for/for-in/switch-case/&&/||
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
        "function_declaration",
        "method_declaration",
        "func_literal",  # Go 的匿名函数
    })

    def _text(self, node) -> str:
        """节点源码文本。"""
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
            if ctype == "if_statement":
                cond = self._extract_if_condition(child)
                out.append({
                    "type": "if",
                    "condition": cond,
                    "line": child.start_point[0] + 1,
                })
            elif ctype == "for_statement":
                cond = self._extract_for_condition(child)
                out.append({
                    "type": "for",
                    "condition": cond,
                    "line": child.start_point[0] + 1,
                })
            elif ctype == "expression_case":
                # switch 的 case 分支
                case_expr = self._extract_case_expr(child)
                out.append({
                    "type": "match_case",
                    "condition": case_expr,
                    "line": child.start_point[0] + 1,
                })
            elif ctype == "default_case":
                out.append({
                    "type": "match_case",
                    "condition": "default",
                    "line": child.start_point[0] + 1,
                })
            elif ctype == "type_case":
                # type switch 的 case
                case_expr = self._extract_case_expr(child)
                out.append({
                    "type": "match_case",
                    "condition": case_expr,
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
        """Go 的 if 结构：if [init;] <cond> { body } [else ...]
        条件是 'if' 关键字后的表达式，在 block 之前。
        """
        # 遍历 children，找 'if' 之后 'block' 之前的表达式
        after_if = False
        cond_parts = []
        for c in if_node.children:
            if c.type == "if":
                after_if = True
                continue
            if not after_if:
                continue
            if c.type == "block":
                break
            if c.type in ("{", "}"):
                break
            # 收集条件表达式（可能有 init statement + cond）
            cond_parts.append(self._text(c))
        return "; ".join(cond_parts).strip()

    def _extract_for_condition(self, for_node) -> str:
        """Go 的 for 语法：
        - for cond { }
        - for init; cond; post { }
        - for i, v := range xs { }
        - for { }（无限循环）
        """
        # 取 'for' 后到 'block' 前的所有内容
        after_for = False
        parts = []
        for c in for_node.children:
            if c.type == "for":
                after_for = True
                continue
            if not after_for:
                continue
            if c.type == "block":
                break
            parts.append(self._text(c))
        text = " ".join(parts).strip()
        return text if text else "infinite"

    def _extract_case_expr(self, case_node) -> str:
        """从 case X: 中提取 X 的文本。"""
        for c in case_node.children:
            if c.type == "expression_list":
                return self._text(c)
            if c.type == "type":
                return self._text(c)
        return ""

    def _extract_returns_info(self, func_node) -> list[dict]:
        """提取函数中所有 return 语句及其守卫条件。

        Go 特色：
            - return 可以返回多值，如 `return 0, err`
            - `panic(...)` 视为 raise
            - `return v, nil` 是成功；`return v, err` 是错误路径
        """
        out: list[dict] = []
        body = None
        for c in func_node.children:
            if c.type == "block":
                body = c
                break
        if body is None:
            return out

        # 从 body 里收集所有 statements（Go 的 block 里通常包一层 statement_list）
        stmts = self._flatten_go_block(body)
        self._collect_returns_from_body(stmts, out, guards=[], depth=0)
        return out

    def _flatten_go_block(self, body) -> list:
        """展开 Go 的 block，跳过 { } 并展开 statement_list。"""
        out: list = []
        for c in body.children:
            if c.type in ("{", "}"):
                continue
            if c.type == "statement_list":
                for inner in c.children:
                    if inner.type not in ("{", "}"):
                        out.append(inner)
            else:
                out.append(c)
        return out

    def _collect_returns_from_body(self, stmts, out, guards, depth=0):
        """按顺序处理语句列表，early-return 后累积 negation guard。"""
        implicit: list[str] = []
        for stmt in stmts:
            self._collect_returns_from_stmt(
                stmt, out, guards + implicit, depth
            )
            if stmt.type == "if_statement":
                if self._is_if_without_else(stmt):
                    if self._if_then_terminates(stmt):
                        cond = self._extract_if_condition(stmt)
                        implicit.append(f"not ({cond})")

    def _is_if_without_else(self, if_node) -> bool:
        """Go 的 if_statement 结构：'if' <cond> <block> ['else' <if or block>]
        通过检查是否有第 2 个 block 或紧跟的 if_statement 来判断。
        """
        seen_block = False
        for c in if_node.children:
            if c.type == "block":
                if seen_block:
                    return False  # 第 2 个 block 说明有 else
                seen_block = True
            elif c.type == "if_statement" and seen_block:
                return False  # else if
        return True

    def _if_then_terminates(self, if_node) -> bool:
        then_block = None
        for c in if_node.children:
            if c.type == "block":
                then_block = c
                break
        if then_block is None:
            return False
        return self._body_terminates(then_block)

    def _body_terminates(self, body_node) -> bool:
        """判断一个 block 是否必然以 return/panic 结束。"""
        if body_node.type != "block":
            return False
        stmts = self._flatten_go_block(body_node)
        if not stmts:
            return False
        last = stmts[-1]
        if last.type == "return_statement":
            return True
        # panic(...) 也算 terminates
        if last.type == "expression_statement":
            for c in last.children:
                if c.type == "call_expression":
                    func_name = self._get_call_name(c)
                    if func_name == "panic":
                        return True
        if last.type == "if_statement":
            if self._is_if_without_else(last):
                return False
            # 找 then block 和 else block/if
            blocks = [c for c in last.children if c.type == "block"]
            else_if = None
            seen_block = False
            for c in last.children:
                if c.type == "block":
                    seen_block = True
                elif c.type == "if_statement" and seen_block:
                    else_if = c
            if len(blocks) >= 2:
                return (
                    self._body_terminates(blocks[0])
                    and self._body_terminates(blocks[1])
                )
            if else_if is not None and blocks:
                # else if 分支：检查 then 和 else-if 是否都 terminates
                return False  # 保守：else if 链需要完整分析，暂不处理
        return False

    def _process_block(self, node, out, guards, depth):
        """处理 block 节点，递归其中的语句。"""
        if node.type == "block":
            stmts = self._flatten_go_block(node)
            self._collect_returns_from_body(stmts, out, guards, depth)
        else:
            self._collect_returns_from_stmt(node, out, guards, depth)

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

        # Go 里 panic 是抛异常
        if stype == "expression_statement":
            for c in stmt.children:
                if c.type == "call_expression":
                    # 检查是不是 panic(...)
                    func_name = self._get_call_name(c)
                    if func_name == "panic":
                        value = self._text(c)
                        out.append({
                            "value": value,
                            "kind": "raise",
                            "exception_type": "panic",
                            "guard": (
                                " and ".join(guards) if guards else ""
                            ),
                            "line": stmt.start_point[0] + 1,
                        })
                        return
            # 其他表达式语句不产生 return

        if stype == "if_statement":
            cond = self._extract_if_condition(stmt)
            # if_statement 结构：'if' <cond expr> <block> ['else' <if_statement or block>]
            then_block = None
            else_part = None
            after_block = False
            for c in stmt.children:
                if c.type == "block":
                    if not after_block:
                        then_block = c
                        after_block = True
                    else:
                        else_part = c
                elif c.type == "if_statement" and after_block:
                    else_part = c

            if then_block is not None:
                self._process_block(
                    then_block, out, guards + [cond], depth + 1
                )
            if else_part is not None:
                neg = f"not ({cond})"
                if else_part.type == "if_statement":
                    self._collect_returns_from_stmt(
                        else_part, out, guards + [neg], depth + 1
                    )
                else:
                    self._process_block(
                        else_part, out, guards + [neg], depth + 1
                    )
            return

        if stype == "for_statement":
            # 循环体内的 return 视为无额外守卫
            for c in stmt.children:
                if c.type == "block":
                    self._process_block(c, out, guards, depth + 1)
            return

        if stype == "expression_switch_statement":
            self._collect_switch_returns(stmt, out, guards, depth)
            return

        if stype == "type_switch_statement":
            self._collect_switch_returns(stmt, out, guards, depth)
            return

        if stype == "block":
            self._process_block(stmt, out, guards, depth + 1)
            return

        # 其他语句无 return

    def _collect_switch_returns(self, switch_node, out, guards, depth):
        """处理 expression_switch_statement / type_switch_statement。"""
        for c in switch_node.children:
            if c.type in ("expression_case", "type_case"):
                case_expr = self._extract_case_expr(c)
                case_guard = f"case {case_expr}"
                for inner in c.children:
                    if inner.type in ("case", ":", "expression_list", "type"):
                        continue
                    self._collect_returns_from_stmt(
                        inner, out, guards + [case_guard], depth + 1
                    )
            elif c.type == "default_case":
                for inner in c.children:
                    if inner.type in ("default", ":"):
                        continue
                    self._collect_returns_from_stmt(
                        inner, out, guards + ["default"], depth + 1
                    )

    def _extract_return_value(self, ret_node) -> str:
        """Go 的 return 语句可能是多值：return 0, err
        整体作为字符串返回。
        """
        skip = {"return", ";"}
        parts = []
        for c in ret_node.children:
            if c.type in skip:
                continue
            if c.type == "expression_list":
                return self._text(c)
            parts.append(self._text(c))
        if parts:
            return ", ".join(parts)
        return ""  # 裸 return（无返回值）

    def _get_call_name(self, call_node) -> str:
        """从 call_expression 提取被调用的函数名。"""
        for c in call_node.children:
            if c.type == "identifier":
                return self._text(c)
            if c.type == "selector_expression":
                return self._text(c)
        return ""

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
