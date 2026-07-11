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
        branches_info = self._extract_branches_info(node)
        returns_info = self._extract_returns_info(node)
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
            "returns_info": returns_info,
            "decorators": decorators if decorators else [],
            "docstring": None,
            "branches": branches,
            "branches_info": branches_info,
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

    # ------------------------------------------------------------------
    # branches_info / returns_info 提取（用例设计增强）
    # ------------------------------------------------------------------

    _NESTED_TYPES = frozenset({
        "method_declaration",
        "constructor_declaration",
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "lambda_expression",
    })

    def _text(self, node) -> str:
        return node.text.decode("utf-8")

    def _condition_from_paren(self, paren_node) -> str:
        for c in paren_node.children:
            if c.type not in ("(", ")"):
                return self._text(c)
        raw = self._text(paren_node).strip()
        if raw.startswith("(") and raw.endswith(")"):
            return raw[1:-1].strip()
        return raw

    def _extract_branches_info(self, method_node) -> list[dict]:
        """提取分支详细信息。不下钻嵌套类/方法。"""
        out: list[dict] = []
        self._collect_branches_info(method_node, out, depth=0)
        return out

    def _collect_branches_info(self, node, out, depth=0):
        if depth > 200:
            return
        for child in node.children:
            ctype = child.type
            if ctype in self._NESTED_TYPES:
                continue
            if ctype == "if_statement":
                cond = self._extract_if_condition(child)
                out.append({
                    "type": "if",
                    "condition": cond,
                    "line": child.start_point[0] + 1,
                })
            elif ctype in ("for_statement", "enhanced_for_statement"):
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
                exc_type = self._extract_catch_type(child)
                out.append({
                    "type": "except",
                    "condition": exc_type,
                    "exception_type": exc_type,
                    "line": child.start_point[0] + 1,
                })
            elif ctype == "ternary_expression":
                cond = self._extract_ternary_condition(child)
                out.append({
                    "type": "ifexp",
                    "condition": cond,
                    "line": child.start_point[0] + 1,
                })
            elif ctype in (
                "switch_block_statement_group", "switch_rule"
            ):
                # 每个 case 是一个分支
                case_expr = self._extract_switch_case_expr(child)
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
        for c in if_node.children:
            if c.type == "parenthesized_expression":
                return self._condition_from_paren(c)
        return ""

    def _extract_for_condition(self, for_node) -> str:
        raw = self._text(for_node).splitlines()[0]
        start = raw.find("(")
        end = raw.rfind(")")
        if start >= 0 and end > start:
            return raw[start + 1:end].strip()
        return raw.strip()

    def _extract_while_condition(self, w_node) -> str:
        for c in w_node.children:
            if c.type == "parenthesized_expression":
                return self._condition_from_paren(c)
        return ""

    def _extract_ternary_condition(self, tern_node) -> str:
        for c in tern_node.children:
            if c.type not in ("?", ":"):
                return self._text(c)
        return ""

    def _extract_switch_case_expr(self, case_node) -> str:
        """提取 case X: 中 X 的文本。"""
        for c in case_node.children:
            if c.type == "switch_label":
                # switch_label 内是 'case X' 或 'default'
                for sc in c.children:
                    if sc.type not in ("case", "default", ":"):
                        return self._text(sc)
                return self._text(c)
        return ""

    def _extract_catch_type(self, catch_node) -> str:
        """从 catch (SomeException e) 提取异常类型。"""
        for c in catch_node.children:
            if c.type == "catch_formal_parameter":
                for cc in c.children:
                    if cc.type in (
                        "catch_type", "type_identifier",
                        "scoped_type_identifier",
                    ):
                        return self._text(cc)
        return "Exception"

    def _extract_returns_info(self, method_node) -> list[dict]:
        """提取方法中所有 return / throw 及其守卫条件。"""
        out: list[dict] = []
        body = None
        for c in method_node.children:
            if c.type == "block":
                body = c
                break
        if body is None:
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
            if stmt.type == "if_statement":
                if self._is_if_without_else(stmt):
                    if self._if_then_terminates(stmt):
                        cond = self._extract_if_condition(stmt)
                        implicit.append(f"not ({cond})")

    def _is_if_without_else(self, if_node) -> bool:
        for c in if_node.children:
            if c.type == "else":
                return False
        return True

    def _if_then_terminates(self, if_node) -> bool:
        then_body = self._find_if_then_body(if_node)
        if then_body is None:
            return False
        return self._body_terminates(then_body)

    def _find_if_then_body(self, if_node):
        """Java 的 then_body：( ) 之后，else 之前的第一个非空节点。"""
        saw_paren = False
        for c in if_node.children:
            if c.type == "parenthesized_expression":
                saw_paren = True
                continue
            if not saw_paren:
                continue
            if c.type == "else":
                return None
            return c
        return None

    def _find_else_body(self, if_node):
        """Java 的 else_body：else 关键字之后的第一个非空节点。"""
        saw_else = False
        for c in if_node.children:
            if c.type == "else":
                saw_else = True
                continue
            if saw_else:
                return c
        return None

    def _body_terminates(self, body_node) -> bool:
        if body_node.type in ("return_statement", "throw_statement"):
            return True
        if body_node.type == "block":
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
                if self._is_if_without_else(last):
                    return False
                then_body = self._find_if_then_body(last)
                else_body = self._find_else_body(last)
                if then_body and else_body:
                    return (
                        self._body_terminates(then_body)
                        and self._body_terminates(else_body)
                    )
        return False

    def _process_if_body(self, node, out, guards, depth):
        """处理 if 的 body：block 或单条语句。"""
        if node.type == "block":
            stmts = [
                s for s in node.children if s.type not in ("{", "}")
            ]
            self._collect_returns_from_body(
                stmts, out, guards, depth
            )
        else:
            self._collect_returns_from_stmt(node, out, guards, depth)

    def _collect_returns_from_stmt(self, stmt, out, guards, depth=0):
        if depth > 200:
            return
        stype = stmt.type
        if stype in self._NESTED_TYPES:
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
            # Java 里 else 直接跟在 if 后面（可能是 block、语句、或另一个 if）
            # 结构: 'if' '(' expr ')' <then_body> ['else' <else_body>]
            then_body = None
            else_body = None
            saw_paren = False
            saw_else = False
            for c in stmt.children:
                if c.type == "parenthesized_expression":
                    saw_paren = True
                    continue
                if c.type == "else":
                    saw_else = True
                    continue
                if not saw_paren:
                    continue
                if not saw_else and then_body is None:
                    then_body = c
                elif saw_else and else_body is None:
                    else_body = c
                    break

            if then_body is not None:
                self._process_if_body(
                    then_body, out, guards + [cond], depth + 1
                )
            if else_body is not None:
                neg = f"not ({cond})"
                if else_body.type == "if_statement":
                    self._collect_returns_from_stmt(
                        else_body, out, guards + [neg], depth + 1
                    )
                else:
                    self._process_if_body(
                        else_body, out, guards + [neg], depth + 1
                    )
            return

        if stype == "try_statement":
            for c in stmt.children:
                if c.type == "block":
                    for s in c.children:
                        if s.type in ("{", "}"):
                            continue
                        self._collect_returns_from_stmt(
                            s, out, guards, depth + 1
                        )
                elif c.type == "catch_clause":
                    exc_type = self._extract_catch_type(c)
                    for s in c.children:
                        if s.type == "block":
                            for inner in s.children:
                                if inner.type in ("{", "}"):
                                    continue
                                self._collect_returns_from_stmt(
                                    inner, out,
                                    guards + [f"except {exc_type}"],
                                    depth + 1,
                                )
                elif c.type == "finally_clause":
                    for s in c.children:
                        if s.type == "block":
                            for inner in s.children:
                                if inner.type in ("{", "}"):
                                    continue
                                self._collect_returns_from_stmt(
                                    inner, out, guards, depth + 1,
                                )
            return

        if stype in (
            "for_statement", "enhanced_for_statement",
            "while_statement", "do_statement",
        ):
            for c in stmt.children:
                if c.type == "block":
                    for s in c.children:
                        if s.type in ("{", "}"):
                            continue
                        self._collect_returns_from_stmt(
                            s, out, guards, depth + 1
                        )
            return

        if stype == "switch_expression":
            for c in stmt.children:
                if c.type == "switch_block":
                    for case in c.children:
                        if case.type in (
                            "switch_block_statement_group", "switch_rule"
                        ):
                            case_expr = self._extract_switch_case_expr(case)
                            case_guard = f"case {case_expr}"
                            for s in case.children:
                                if s.type in ("switch_label",):
                                    continue
                                self._collect_returns_from_stmt(
                                    s, out, guards + [case_guard],
                                    depth + 1,
                                )
            return

        if stype == "block":
            for s in stmt.children:
                if s.type in ("{", "}"):
                    continue
                self._collect_returns_from_stmt(
                    s, out, guards, depth + 1
                )
            return

    def _extract_return_value(self, ret_node) -> str:
        skip = {"return", ";"}
        for c in ret_node.children:
            if c.type not in skip:
                return self._text(c)
        return "null"

    def _extract_throw_value(self, throw_node) -> str:
        skip = {"throw", ";"}
        for c in throw_node.children:
            if c.type not in skip:
                return self._text(c)
        return "Exception"

    def _extract_throw_type(self, throw_node) -> str:
        for c in throw_node.children:
            if c.type == "object_creation_expression":
                # new SomeException(...)
                for nc in c.children:
                    if nc.type in (
                        "type_identifier", "scoped_type_identifier"
                    ):
                        return self._text(nc)
            if c.type in ("identifier", "type_identifier"):
                return self._text(c)
            if c.type == "method_invocation":
                # 返回被调方法名（少见但可能）
                return self._text(c)
        return "Exception"

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
