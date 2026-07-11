"""四种用例设计共享算法：等价类 / 边界值 / 异常路径 / 决策表。

语言无关的算法逻辑，通过 ``type_boundaries`` 和 ``type_normals``
参数接收每语言独立的数据，实现算法共享、数据隔离。
"""

from typing import Any


# ---------------------------------------------------------------------------
# Severity 分级（用于用例排序和硬性上限筛选）
# ---------------------------------------------------------------------------

# 每种用例类型的默认严重性
DEFAULT_SEVERITY: dict[str, str] = {
    "decision_table": "critical",   # 复杂条件组合，最能暴露 bug
    "exception_path": "high",        # 异常分支覆盖
    "security_test": "high",         # 安全测试
    "boundary_value": "medium",      # 边界值，具体 category 再细分
    "edge_case": "medium",           # 边缘情况
    "equivalence_class": "low",      # 一个函数只一条，覆盖率填充
    "performance": "low",            # 性能基准，多数场景可选
}

# 边界值 category 的加权（影响升级/降级 severity）
# 数字越大，边界越重要。>= 0.8 升 high；<= 0.3 降 low
BOUNDARY_CATEGORY_WEIGHT: dict[str, float] = {
    # 高价值：真实业务经常出问题
    "zero": 1.0,
    "negative": 0.9,
    "empty": 0.9,
    "null": 0.9,
    "none": 0.9,
    "single": 0.7,

    # 中价值
    "max_int": 0.5,
    "min_int": 0.5,
    "positive": 0.4,
    "single_char": 0.4,

    # 低价值
    "large": 0.3,
    "large_negative": 0.2,
    "very_long": 0.3,
    "unicode": 0.6,
    "special_chars": 0.6,
    "whitespace": 0.5,
    "tiny": 0.4,
    "huge": 0.3,
    "infinity": 0.5,
    "nan": 0.5,
    "true": 0.5,
    "false": 0.5,
    "normal": 0.3,
    "with_data": 0.3,
    "binary": 0.4,
}

# 安全测试 category 的加权
SECURITY_CATEGORY_WEIGHT: dict[str, float] = {
    "sql_injection": 1.0,
    "command_injection": 1.0,
    "xss": 0.9,
    "path_traversal": 0.9,
    "ssrf": 0.8,
    "null_byte": 0.6,
}


def _weight_to_severity(weight: float, base: str = "medium") -> str:
    """把 [0.0, 1.0] 权重映射到 severity 等级。

    >= 0.8 → high（除非 base 已经是 critical）
    >= 0.5 → 保持 base
    < 0.5 → low（除非 base 是 critical，不降级）
    """
    if base == "critical":
        return "critical"
    if weight >= 0.8:
        return "high" if base != "high" else "high"
    if weight < 0.4:
        return "low"
    return base


# 用例类型的处理优先级（用于遍历顺序，让覆盖计算更准）
_TYPE_PRIORITY: dict[str, int] = {
    "decision_table": 0,
    "exception_path": 1,
    "boundary_value": 2,
    "security_test": 3,
    "edge_case": 4,
    "equivalence_class": 5,
    "performance": 6,
}


def design_cases(
    analysis: dict,
    type_boundaries: dict,
    type_normals: dict,
    quotas: dict | None = None,
) -> dict:
    """基于分析结果生成测试用例清单。

    按四种方法生成:
        - 等价类划分: 类型注解推导正常值
        - 边界值分析: type_boundaries 映射表
        - 异常路径: 分支数 > 0 时生成
        - 决策表: 分支数 >= 3 时生成

    然后通过 ``prioritize_cases`` 按 severity 排序和硬性上限筛选，
    避免一个函数产生过多用例稀释 LLM 注意力。

    Args:
        analysis: analyze() 的输出
        type_boundaries: 类型 -> 边界值列表
        type_normals: 类型 -> 正常值列表
        quotas: 用例配额配置（默认 DEFAULT_QUOTAS）

    Returns:
        {"test_cases": [...], "summary": {...}}
    """
    all_cases: list[dict] = []  # 排序前的原始用例（用于 summary 统计）
    files = analysis.get("files", [])

    for finfo in files:
        if "error" in finfo:
            continue
        rel = finfo.get("file", "")
        for func in finfo.get("functions", []):
            cases = _gen_for_function(
                rel, func, type_boundaries, type_normals
            )
            all_cases.extend(cases)
        for cls in finfo.get("classes", []):
            for method in cls.get("methods", []):
                cases = _gen_for_function(
                    rel, method, type_boundaries, type_normals
                )
                all_cases.extend(cases)

    # 按 target 分组，各自 prioritize
    test_cases: list[dict] = []
    groups = _group_cases_by_target(all_cases)
    for target_cases in groups.values():
        test_cases.extend(prioritize_cases(target_cases, quotas))

    summary = {
        "total_cases": len(test_cases),
        "raw_total": len(all_cases),
        "filtered_out": len(all_cases) - len(test_cases),
        "by_type": _count_by_type(test_cases),
        "by_severity": _count_by_severity(test_cases),
    }
    return {"test_cases": test_cases, "summary": summary}


def _resolve_type(annotation: str, type_normals: dict) -> str:
    """从类型注解提取核心类型名，支持 Optional/Union/PEP 604 复合注解。

    支持的语法:
        - int
        - Optional[int]
        - Union[int, str]
        - Union[int, None]
        - int | str          (PEP 604, Python 3.10+)
        - int | None         (PEP 604)
        - Optional[int] | None
    """
    if not annotation:
        return ""
    # PEP 604: X | Y | Z
    if "|" in annotation and not annotation.startswith(("Optional[", "Union[")):
        for part in annotation.split("|"):
            part = part.strip()
            if part and part != "None" and part in type_normals:
                return part
        # 没有已知类型，返回第一个非 None 部分
        for part in annotation.split("|"):
            part = part.strip()
            if part and part != "None":
                return part
        return annotation
    # Optional[X] / Union[X, Y]
    for prefix in ("Optional[", "Union["):
        if annotation.startswith(prefix):
            inner = annotation[len(prefix):-1]
            for part in inner.split(","):  # noqa
                part = part.strip()
                if part and part != "None" and part in type_normals:
                    return part
            # 没有已知类型，返回第一个非 None 部分
            for part in inner.split(","):
                part = part.strip()
                if part and part != "None":
                    return part
    return annotation


def _gen_for_function(
    rel_file: str,
    func: dict,
    type_boundaries: dict,
    type_normals: dict,
) -> list[dict]:
    """为单个函数/方法生成用例。"""
    cases: list[dict] = []
    name = func.get("qualname") or func.get("name", "unknown")
    branches = func.get("branches", 0)
    args = [a for a in func.get("args", []) if a.get("kind") is None]
    has_self = bool(args) and args[0]["name"] in ("self", "cls")
    relevant_args = args[1:] if has_self else args

    # 等价类划分
    normal_inputs = _build_normal_inputs(relevant_args, type_normals)
    returns_info = func.get("returns_info", [])
    eq_expected = _format_equivalence_expected(returns_info)
    cases.append(
        {
            "target": name,
            "file": rel_file,
            "type": "equivalence_class",
            "description": f"{name} 正常输入等价类",
            "inputs": normal_inputs,
            "expected": eq_expected,
            "severity": DEFAULT_SEVERITY["equivalence_class"],
        }
    )

    # 边界值分析
    boundary_cases = _build_boundary_cases(
        name, rel_file, relevant_args, type_boundaries, type_normals
    )
    cases.extend(boundary_cases)

    # 异常路径
    if branches > 0:
        branches_info = func.get("branches_info", [])
        returns_info = func.get("returns_info", [])
        # 从 branches_info 提取具体的分支描述
        cond_descs = _summarize_branch_conditions(branches_info)
        return_desc = _summarize_returns(returns_info)
        parts: list[str] = []
        if cond_descs:
            parts.append(f"覆盖以下分支路径: {cond_descs}")
        if return_desc:
            parts.append(f"预期返回/异常: {return_desc}")
        if parts:
            expected_text = "；".join(parts)
        else:
            expected_text = "覆盖各分支路径，验证返回值或异常"
        cases.append(
            {
                "target": name,
                "file": rel_file,
                "type": "exception_path",
                "description": f"{name} 分支覆盖（{branches} 个分支节点）",
                "inputs": normal_inputs,
                "expected": expected_text,
                "severity": DEFAULT_SEVERITY["exception_path"],
            }
        )

    # 决策表
    if branches >= 3:
        branches_info = func.get("branches_info", [])
        returns_info = func.get("returns_info", [])
        decision_cases = _build_decision_cases_from_branches(
            name, rel_file, relevant_args, branches_info,
            type_normals, func.get("complexity", "?"),
            returns_info=returns_info,
        )
        if decision_cases:
            cases.extend(decision_cases)
        else:
            # 回退：无分支信息时使用简单占位组合
            cases.append(
                {
                    "target": name,
                    "file": rel_file,
                    "type": "decision_table",
                    "description": (
                        f"{name} 复杂分支决策表（complexity="
                        f"{func.get('complexity', '?')}）"
                    ),
                    "inputs": _build_decision_inputs(
                        relevant_args, type_normals
                    ),
                    "expected": "每个条件组合产生预期结果",
                    "severity": DEFAULT_SEVERITY["decision_table"],
                }
            )

    # 边缘情况
    edge_cases = _build_edge_cases(
        name, rel_file, relevant_args, type_boundaries, type_normals
    )
    cases.extend(edge_cases)

    # 安全性测试
    security_cases = _build_security_cases(
        name, rel_file, relevant_args, type_boundaries, type_normals
    )
    cases.extend(security_cases)

    # 性能基准测试
    performance_cases = _build_performance_cases(
        name, rel_file, relevant_args, type_boundaries, type_normals
    )
    cases.extend(performance_cases)

    return cases


def _build_normal_inputs(
    args: list[dict], type_normals: dict
) -> dict[str, str]:
    """构建等价类正常输入。"""
    inputs: dict[str, str] = {}
    fallback = _resolve_lang_none(type_normals)
    for arg in args:
        ann = arg.get("annotation")
        default = arg.get("default")
        if default is not None:
            inputs[arg["name"]] = default
        elif ann:
            resolved = _resolve_type(ann, type_normals)
            if resolved in type_normals:
                inputs[arg["name"]] = type_normals[resolved][0]
            else:
                inputs[arg["name"]] = fallback
        else:
            inputs[arg["name"]] = fallback
    return inputs


def _build_boundary_cases(
    name: str,
    rel_file: str,
    args: list[dict],
    type_boundaries: dict,
    type_normals: dict,
) -> list[dict]:
    """构建边界值用例。"""
    cases: list[dict] = []
    for arg in args:
        ann = arg.get("annotation")
        if not ann:
            continue
        resolved = _resolve_type(ann, type_normals)
        if resolved not in type_boundaries:
            continue
        for bv in type_boundaries[resolved]:
            inputs: dict[str, str] = {}
            for other in args:
                if other["name"] == arg["name"]:
                    inputs[other["name"]] = bv["value"]
                elif other.get("default") is not None:
                    inputs[other["name"]] = other["default"]
                else:
                    other_ann = other.get("annotation")
                    if other_ann:
                        other_type = _resolve_type(other_ann, type_normals)
                        if other_type in type_normals:
                            inputs[other["name"]] = type_normals[
                                other_type
                            ][0]
                        else:
                            inputs[other["name"]] = "None"
                    else:
                        inputs[other["name"]] = "None"
            cases.append(
                {
                    "target": name,
                    "file": rel_file,
                    "type": "boundary_value",
                    "description": (
                        f"{name} 参数 {arg['name']} "
                        f"边界值 ({bv['category']})"
                    ),
                    "inputs": inputs,
                    "expected": "验证边界行为，可能返回或抛出预期异常",
                    "severity": _weight_to_severity(
                        BOUNDARY_CATEGORY_WEIGHT.get(bv["category"], 0.5),
                        base=DEFAULT_SEVERITY["boundary_value"],
                    ),
                }
            )
    return cases


def _build_decision_inputs(
    args: list[dict], type_normals: dict
) -> list[dict]:
    """构建决策表条件组合。"""
    combos: list[dict] = []
    typed = [
        a
        for a in args
        if _resolve_type(a.get("annotation", ""), type_normals)
        in type_normals
    ]
    if not typed:
        combos.append(_build_normal_inputs(args, type_normals))
        return combos
    first = typed[0]
    first_type = _resolve_type(first["annotation"], type_normals)
    for val in type_normals.get(first_type, ["None"])[:2]:
        combo = _build_normal_inputs(args, type_normals)
        combo[first["name"]] = val
        combos.append(combo)
    return combos


def _build_edge_cases(
    name: str,
    rel_file: str,
    args: list[dict],
    type_boundaries: dict,
    type_normals: dict,
) -> list[dict]:
    """构建边缘情况用例。

    专门筛选 type_boundaries 中 category 为以下的用例：
    - null_byte
    - max_int / min_int
    - infinity / nan
    - empty / single / None
    - xss / security
    """
    cases: list[dict] = []
    edge_categories = {
        "null_byte", "max_int", "min_int", "infinity", "nan",
        "xss", "security", "empty", "none"
    }

    for arg in args:
        ann = arg.get("annotation")
        if not ann:
            continue
        resolved = _resolve_type(ann, type_normals)
        if resolved not in type_boundaries:
            continue

        for bv in type_boundaries[resolved]:
            if bv.get("category") not in edge_categories:
                continue

            inputs: dict[str, str] = {}
            for other in args:
                if other["name"] == arg["name"]:
                    inputs[other["name"]] = bv["value"]
                elif other.get("default") is not None:
                    inputs[other["name"]] = other["default"]
                else:
                    other_ann = other.get("annotation")
                    if other_ann:
                        other_type = _resolve_type(other_ann, type_normals)
                        if other_type in type_normals:
                            inputs[other["name"]] = type_normals[other_type][0]
                        else:
                            inputs[other["name"]] = "None"
                    else:
                        inputs[other["name"]] = "None"

            cases.append({
                "target": name,
                "file": rel_file,
                "type": "edge_case",
                "description": (
                    f"{name} 参数 {arg['name']} 边缘情况 ({bv['category']})"
                ),
                "inputs": inputs,
                "expected": "验证极端边缘情况的行为，不崩溃",
                "severity": DEFAULT_SEVERITY["edge_case"],
            })
    return cases


def _build_security_cases(
    name: str,
    rel_file: str,
    args: list[dict],
    type_boundaries: dict,
    type_normals: dict,
) -> list[dict]:
    """构建安全性测试用例。

    专门筛选 type_boundaries 中 category 为以下的用例：
    - xss
    - security
    - sql_injection
    - command_injection
    """
    cases: list[dict] = []
    security_categories = {
        "xss", "security", "sql_injection", "command_injection",
        "path_traversal", "ssrf"
    }

    for arg in args:
        ann = arg.get("annotation")
        if not ann:
            continue
        resolved_type = _resolve_type(ann, type_normals)
        if resolved_type not in type_boundaries:
            continue

        for bv in type_boundaries[resolved_type]:
            if bv.get("category") not in security_categories:
                continue

            inputs: dict[str, str] = {}
            for other in args:
                if other["name"] == arg["name"]:
                    inputs[other["name"]] = bv["value"]
                elif other.get("default") is not None:
                    inputs[other["name"]] = other["default"]
                else:
                    other_ann = other.get("annotation")
                    if other_ann:
                        other_resolved = _resolve_type(other_ann, type_normals)
                        if other_resolved in type_normals:
                            inputs[other["name"]] = type_normals[other_resolved][0]
                        else:
                            inputs[other["name"]] = "None"
                    else:
                        inputs[other["name"]] = "None"

            cases.append({
                "target": name,
                "file": rel_file,
                "type": "security_test",
                "description": (
                    f"{name} 参数 {arg['name']} 安全测试 ({bv['category']})"
                ),
                "inputs": inputs,
                "expected": "验证输入处理不会引入安全漏洞",
                "severity": _weight_to_severity(
                    SECURITY_CATEGORY_WEIGHT.get(bv["category"], 0.7),
                    base=DEFAULT_SEVERITY["security_test"],
                ),
            })
    return cases


def _build_performance_cases(
    name: str,
    rel_file: str,
    args: list[dict],
    type_boundaries: dict,
    type_normals: dict,
) -> list[dict]:
    """构建性能基准测试用例。

    专门筛选 type_boundaries 中 category 为以下的用例：
    - large
    - huge
    - very_long
    - performance
    """
    cases: list[dict] = []
    performance_categories = {
        "large", "huge", "very_long", "performance", "large_negative"
    }

    for arg in args:
        ann = arg.get("annotation")
        if not ann:
            continue
        resolved_type = _resolve_type(ann, type_normals)
        if resolved_type not in type_boundaries:
            continue

        for bv in type_boundaries[resolved_type]:
            if bv.get("category") not in performance_categories:
                continue

            inputs: dict[str, str] = {}
            for other in args:
                if other["name"] == arg["name"]:
                    inputs[other["name"]] = bv["value"]
                elif other.get("default") is not None:
                    inputs[other["name"]] = other["default"]
                else:
                    other_ann = other.get("annotation")
                    if other_ann:
                        other_resolved = _resolve_type(other_ann, type_normals)
                        if other_resolved in type_normals:
                            inputs[other["name"]] = type_normals[other_resolved][0]
                        else:
                            inputs[other["name"]] = "None"
                    else:
                        inputs[other["name"]] = "None"

            cases.append({
                "target": name,
                "file": rel_file,
                "type": "performance",
                "description": (
                    f"{name} 参数 {arg['name']} 性能测试 ({bv['category']})"
                ),
                "inputs": inputs,
                "expected": "验证大数据量/极端输入下的性能表现",
                "severity": DEFAULT_SEVERITY["performance"],
            })
    return cases


def _count_by_type(cases: list[dict]) -> dict[str, int]:
    """统计用例类型分布。"""
    counts: dict[str, int] = {}
    for c in cases:
        t = c.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return counts


def _filter_cases(cases: list[dict], func_info: dict) -> list[dict]:
    """根据函数复杂度智能筛选测试用例。

    筛选规则:
        - 简单函数（分支数 <= 1）：只保留核心用例
        - 中等函数（分支数 2-4）：保留大部分用例
        - 复杂函数（分支数 >= 5）：保留全部用例

    核心用例优先: equivalence_class > exception_path > security_test >
                    boundary_value > edge_case > decision_table > performance

    Args:
        cases: 生成的所有测试用例
        func_info: 函数信息，包含 branches、complexity 等字段

    Returns:
        筛选后的测试用例列表
    """
    if not cases:
        return []

    branches = func_info.get("branches", 0)

    # 优先级排序：核心测试 > 安全测试 > 边界值 > 其他
    priority = {
        "equivalence_class": 7,
        "exception_path": 6,
        "security_test": 5,
        "boundary_value": 4,
        "edge_case": 3,
        "decision_table": 2,
        "performance": 1,
    }

    # 根据分支数决定保留比例
    if branches <= 1:
        # 简单函数：只保留高优先级的用例，避免测试过多
        filtered = []
        for case in cases:
            case_type = case.get("type", "")
            # 简单函数只保留最核心的用例
            if priority.get(case_type, 0) >= 5:
                filtered.append(case)
            elif priority.get(case_type, 0) >= 4:
                # 边界值每个类型只保留1-2个
                if len([c for c in filtered if c.get("type") == case_type]) < 2:
                    filtered.append(case)
        return filtered

    elif branches <= 4:
        # 中等复杂度：保留大部分，但稍微裁剪
        filtered = []
        for case in cases:
            case_type = case.get("type", "")
            if priority.get(case_type, 0) >= 3:
                filtered.append(case)
            elif priority.get(case_type, 0) >= 2:
                if len([c for c in filtered if c.get("type") == case_type]) < 3:
                    filtered.append(case)
        return filtered

    else:
        # 复杂函数：保留全部用例，确保充分覆盖
        return cases


# ---------------------------------------------------------------------------
# 基于 branches_info 的决策表增强
# ---------------------------------------------------------------------------

import re


def _summarize_branch_conditions(
    branches_info: list[dict], limit: int = 3
) -> str:
    """把分支信息汇总为一行文本，用于 expected 字段。"""
    if not branches_info:
        return ""
    parts: list[str] = []
    for b in branches_info[:limit]:
        btype = b.get("type", "")
        cond = b.get("condition", "")
        if not cond:
            continue
        if btype == "if" or btype == "ifexp":
            parts.append(f"if {cond}")
        elif btype == "except":
            parts.append(f"except {cond}")
        elif btype == "for":
            parts.append(f"for {cond}")
        elif btype == "while":
            parts.append(f"while {cond}")
        elif btype == "match_case":
            parts.append(f"case {cond}")
        # boolop 不单独列出，通常已包含在 if 里
    if len(branches_info) > limit:
        parts.append(f"...(+{len(branches_info) - limit} 个)")
    return "；".join(parts)


# 简单的标识符匹配（不区分变量/函数名，够用即可）
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# 关键字/字面量白名单，不视作变量
_KEYWORD_BLACKLIST = frozenset({
    "True", "False", "None", "and", "or", "not", "in", "is",
    "if", "else", "elif", "for", "while", "return",
    # JS/TS/Java 常见字面量与关键字
    "true", "false", "null", "undefined", "typeof", "instanceof",
    "new", "this", "void",
    # Go/Rust
    "nil", "let", "match", "self", "mut",
})


def _extract_condition_variables(condition: str) -> list[str]:
    """从条件表达式提取候选变量名。

    跳过:
        - 关键字/字面量（True/False/None/null/typeof 等）
        - 属性访问 `.x`（右侧标识符视为属性名，不是变量）
        - 函数调用 `x(...)`（左侧标识符视为函数名，不是被测变量）
        - 命名空间路径 `A::B` 里 `::` 后的标识符
    """
    if not condition:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for m in _IDENT_RE.finditer(condition):
        name = m.group()
        if name in _KEYWORD_BLACKLIST:
            continue
        start, end = m.start(), m.end()
        # 跳过前面紧跟 . / :: 的标识符（属性访问 / 命名空间）
        if start >= 1 and condition[start - 1] == ".":
            continue
        if start >= 2 and condition[start - 2:start] == "::":
            continue
        # 跳过后面紧跟 ( 的标识符（函数调用）
        if end < len(condition) and condition[end] == "(":
            continue
        if name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _var_boundary(var_name: str) -> str:
    """返回带前后向断言的严格变量匹配正则片段。

    前后不能是 . _ 字母数字 (，避免误匹配:
        - obj.x 里的 x（前面是 .）
        - x.attr 里的 x（后面是 .）
        - xx 里的第二个 x（前后是字母）
        - x(...) 里的 x（后面是 (，是函数调用）
    """
    esc = re.escape(var_name)
    return rf"(?<![.\w]){esc}(?![.\w(])"


def _guess_boundary_from_comparison(
    condition: str, var_name: str
) -> tuple[str, str] | None:
    """从 `x >= 9900` / `x == 2` 类比较中猜测使条件为真/假的值。

    支持:
        - Python: ==, !=, >=, <=, >, <
        - JS: ===, !==, >=, <=, >, <
        - 布尔上下文: `x` 单独出现 (视为 true / false)
        - 取反: `!x` / `not x` 会交换 true/false

    Returns:
        (true_value, false_value) 或 None（未匹配到简单比较）
    """
    var_re = _var_boundary(var_name)
    # 匹配 var op literal 或 literal op var
    # 注意顺序: 长的 op 在前，避免 === 被截为 ==
    patterns = [
        # var op num（op = ===, !==, ==, !=, >=, <=, >, <）
        rf"{var_re}\s*(===|!==|==|!=|>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)",
        # var op "str" or 'str'
        rf"{var_re}\s*(===|!==|==|!=)\s*([\"'][^\"']*[\"'])",
        # num op var（反向）
        rf"(-?\d+(?:\.\d+)?)\s*(===|!==|==|!=|>=|<=|>|<)\s*{var_re}",
    ]
    for pat in patterns:
        m = re.search(pat, condition)
        if not m:
            continue
        g = m.groups()
        # 判断是正向 (var op literal) 还是反向 (literal op var)
        if g[0] in ("===", "!==", "==", "!=", ">=", "<=", ">", "<"):
            op, literal = g[0], g[1]
            reverse = False
        else:
            literal, op = g[0], g[1]
            reverse = True
        # 归一化 JS 的 === / !== 到 == / !=
        op_norm = op.replace("===", "==").replace("!==", "!=")
        # 数字场景
        if re.match(r"^-?\d+(?:\.\d+)?$", literal):
            try:
                num = float(literal) if "." in literal else int(literal)
            except ValueError:
                continue
            true_v, false_v = _numeric_true_false(op_norm, num, reverse)
            return (str(true_v), str(false_v))
        # 字符串场景
        if op_norm == "==":
            return (literal, '""')
        if op_norm == "!=":
            return ('""', literal)

    # 布尔上下文：var 单独作为布尔条件出现
    # 严格边界 + 排除函数调用参数（避免 len(x) > 0 里的 x 被视为布尔）
    if _is_bare_boolean(condition, var_name):
        negated = _is_boolean_negated(condition, var_name)
        # 让条件为真：如果被取反了，需要变量为 false；否则变量为 true
        if negated:
            return ("__LANG_FALSE__", "__LANG_TRUE__")
        return ("__LANG_TRUE__", "__LANG_FALSE__")
    return None


def _is_bare_boolean(condition: str, var_name: str) -> bool:
    """判断 var_name 是否作为顶层布尔变量出现（不是被 len()/.attr 等包裹）。

    示例:
        `isPass` → True
        `!isValid` → True
        `not enabled` → True
        `a && b` （对 b） → True
        `len(x) > 0` （对 x） → False（x 在函数调用参数里）
        `obj.x` （对 x） → False（属性访问）
        `x.length > 0` （对 x） → False（x 后跟 . 是成员访问，不是纯布尔）
    """
    esc = re.escape(var_name)
    for m in re.finditer(rf"\b{esc}\b", condition):
        start, end = m.start(), m.end()
        prev = condition[start - 1] if start > 0 else " "
        # 前面不能是 . _ 字母数字（避免 obj.x / xx）
        if prev in "._" or prev.isalnum():
            continue
        nxt = condition[end] if end < len(condition) else " "
        # 后面不能是 . [ ( _ 字母数字（避免 x.a / x[0] / x() / xx）
        if nxt in "._[(" or nxt.isalnum():
            continue
        # 前面是 ( 时判断是不是函数调用参数
        if prev == "(":
            # 找 ( 之前的第一个非空白字符
            i = start - 2
            while i >= 0 and condition[i].isspace():
                i -= 1
            if i >= 0 and (condition[i].isalnum() or condition[i] == "_"):
                # 前面是标识符 + (，说明是函数调用
                continue
        return True
    return False


def _is_boolean_negated(condition: str, var_name: str) -> bool:
    """检查 var_name 是否被 ! 或 not 取反。"""
    neg_pat = rf"(!\s*|\bnot\s+){re.escape(var_name)}\b"
    return bool(re.search(neg_pat, condition))


def _numeric_true_false(
    op: str, num, reverse: bool
) -> tuple:
    """给定 var op num（reverse=True 表示 num op var），返回 (true_v, false_v)。"""
    # 通过对调 op 处理反向
    if reverse:
        op = {">": "<", "<": ">", ">=": "<=", "<=": ">="}.get(op, op)
    if isinstance(num, float):
        step = 1.0
    else:
        step = 1
    if op == "==":
        return (num, num + step)
    if op == "!=":
        return (num + step, num)
    if op == ">=":
        return (num, num - step)
    if op == ">":
        return (num + step, num)
    if op == "<=":
        return (num, num + step)
    if op == "<":
        return (num - step, num)
    return (num, num + step)


def _default_value_for_arg(arg: dict, type_normals: dict) -> str:
    """为参数生成默认值（不参与条件时的填充值）。"""
    default = arg.get("default")
    if default is not None:
        return default
    ann = arg.get("annotation")
    if ann:
        # 简单类型直接查表
        for key in type_normals:
            if key in ann:
                return type_normals[key][0]
    # 无类型注解：返回该语言的 null/None 字面量
    return _resolve_lang_none(type_normals)


def _resolve_lang_bool(type_normals: dict) -> tuple[str, str]:
    """从 type_normals 中查找布尔字面量。

    Python: "bool" → ["True", "False"]
    JS/TS:  "boolean" → ["true", "false"]
    Go:     "bool" → ["true", "false"]
    """
    for key in ("bool", "boolean"):
        vals = type_normals.get(key)
        if vals and len(vals) >= 2:
            return (vals[0], vals[1])
    return ("True", "False")


def _resolve_lang_none(type_normals: dict) -> str:
    """从 type_normals 中查找 null/None 字面量。

    Python: "None" → ["None"]
    JS/TS:  "null" → ["null"]
    Go:     "nil"（若存在）
    """
    for key in ("None", "null", "nil"):
        vals = type_normals.get(key)
        if vals:
            return vals[0]
    return "None"


def _build_decision_cases_from_branches(
    name: str,
    rel_file: str,
    args: list[dict],
    branches_info: list[dict],
    type_normals: dict,
    complexity,
    returns_info: list[dict] | None = None,
) -> list[dict]:
    """基于真实分支条件生成决策表用例。

    策略:
        - 只处理 if / ifexp / while 类的条件分支
        - 每个 if 分支生成 2 个用例：条件为真、条件为假
        - 至多生成 4 个决策用例，避免爆炸
        - 若提供 returns_info，则把匹配 guard 的 return/raise 值写入 expected
    """
    if not branches_info:
        return []

    returns_info = returns_info or []
    lang_true, lang_false = _resolve_lang_bool(type_normals)
    lang_none = _resolve_lang_none(type_normals)

    # 过滤出可用的条件分支（if / ifexp / while）
    conditional = [
        b for b in branches_info
        if b.get("type") in ("if", "ifexp", "while") and b.get("condition")
    ]
    if not conditional:
        return []

    arg_names = {a["name"] for a in args}
    cases: list[dict] = []

    # 每个 if 分支单独生成真/假两个用例
    for branch in conditional[:2]:  # 最多前 2 个分支，避免用例过多
        cond_expr = branch["condition"]
        variables = _extract_condition_variables(cond_expr)
        # 只保留出现在参数里的变量
        relevant_vars = [v for v in variables if v in arg_names]
        if not relevant_vars:
            continue

        # 为每个变量猜测真/假值
        true_inputs: dict[str, str] = {}
        false_inputs: dict[str, str] = {}
        matched_any = False
        for var in relevant_vars:
            guessed = _guess_boundary_from_comparison(cond_expr, var)
            if guessed:
                t_val, f_val = guessed
                # 布尔占位符按语言替换
                if t_val == "__LANG_TRUE__":
                    t_val = lang_true
                if f_val == "__LANG_FALSE__":
                    f_val = lang_false
                true_inputs[var] = t_val
                false_inputs[var] = f_val
                matched_any = True
            else:
                # 未匹配到简单比较，使用类型正常值
                arg = next((a for a in args if a["name"] == var), None)
                if arg:
                    default_val = _default_value_for_arg(arg, type_normals)
                    true_inputs[var] = default_val
                    false_inputs[var] = default_val

        # 填充其他参数的默认值
        for a in args:
            if a["name"] not in true_inputs:
                dv = _default_value_for_arg(a, type_normals)
                true_inputs[a["name"]] = dv
                false_inputs[a["name"]] = dv

        # 从 returns_info 查询匹配的返回值/异常
        true_ret = _find_return_for_condition(returns_info, cond_expr, True)
        false_ret = _find_return_for_condition(returns_info, cond_expr, False)

        # True 用例
        true_expected = f"当 {cond_expr} 时执行对应分支"
        if true_ret:
            true_expected = _format_return_expected(cond_expr, true_ret)
        cases.append({
            "target": name,
            "file": rel_file,
            "type": "decision_table",
            "description": (
                f"{name} 决策表: 条件 `{cond_expr}` 为真"
            ),
            "inputs": true_inputs,
            "expected": true_expected,
            "severity": DEFAULT_SEVERITY["decision_table"],
        })
        if matched_any:
            false_expected = f"当条件 `{cond_expr}` 不成立时走 else/其他分支"
            if false_ret:
                false_expected = _format_return_expected(
                    f"条件 `{cond_expr}` 不成立", false_ret
                )
            cases.append({
                "target": name,
                "file": rel_file,
                "type": "decision_table",
                "description": (
                    f"{name} 决策表: 条件 `{cond_expr}` 为假"
                ),
                "inputs": false_inputs,
                "expected": false_expected,
                "severity": DEFAULT_SEVERITY["decision_table"],
            })

        if len(cases) >= 4:
            break

    return cases


def _summarize_returns(returns_info: list[dict], limit: int = 4) -> str:
    """把 returns_info 汇总为一行文本。"""
    if not returns_info:
        return ""
    parts: list[str] = []
    for r in returns_info[:limit]:
        kind = r.get("kind", "return")
        value = r.get("value", "?")
        guard = _prettify_guard(r.get("guard", "")) or "无条件"
        if kind == "raise":
            parts.append(f"raise {value} when {guard}")
        else:
            parts.append(f"return {value} when {guard}")
    if len(returns_info) > limit:
        parts.append(f"...(+{len(returns_info) - limit} 项)")
    return "；".join(parts)


def _prettify_guard(guard: str) -> str:
    """把内部使用的 guard 字符串转为面向用户的可读描述。

    内部 guard 用 `not (X)` 表示否定，`Y and Z` 表示与关系（跨语言统一）。
    展示给用户时替换为中文，避免和 JS/Java/Go/Rust 的语法冲突。
    """
    if not guard:
        return ""
    result = guard
    # 用递归 balance-aware 替换 `not (X)` → `非 (X)`
    result = _replace_not_wrapper(result)
    # `A and B and C` → `A 且 B 且 C`（顶层 and 才替换，避免碰字符串字面量）
    parts = _split_top_level_and(result)
    if len(parts) > 1:
        result = " 且 ".join(parts)
    return result


def _replace_not_wrapper(expr: str) -> str:
    """把 expr 里所有的 `not (…)` 顶层出现替换为 `非 (…)`。

    只替换正则边界后的 `not `（前面是空格 / 起始 / 括号），
    避免把 `cannot` / `snot` 等字符串误伤。
    """
    out = []
    i = 0
    n = len(expr)
    while i < n:
        # 检测 "not (" 的起点：前面是起始 / 空白 / (
        if (
            expr[i:i + 5] == "not ("
            and (i == 0 or expr[i - 1] in " ()")
        ):
            # 找到对应的 )
            depth = 0
            j = i + 4  # 指到 (
            while j < n:
                if expr[j] == "(":
                    depth += 1
                elif expr[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j < n and depth == 0:
                # 替换 not (X) → 非 (X)
                inner = expr[i + 5:j]
                out.append(f"非 ({inner})")
                i = j + 1
                continue
        out.append(expr[i])
        i += 1
    return "".join(out)


def _find_return_for_condition(
    returns_info: list[dict],
    cond_expr: str,
    positive: bool,
) -> dict | None:
    """从 returns_info 找到 guard 与给定条件匹配的 return。

    正向 (positive=True):  guard 包含 `cond_expr` 且不包含 `not (cond_expr)` 的
    反向 (positive=False): guard 显式包含 `not (cond_expr)` 的
    """
    if not returns_info:
        return None
    cond_norm = cond_expr.strip()
    neg_marker = f"not ({cond_norm})"
    if positive:
        # 优先：guard 完全等于 cond_expr
        for r in returns_info:
            guard = r.get("guard", "")
            if guard == cond_norm:
                return r
        # 次优：guard 包含 cond_expr 但不包含它的否定
        for r in returns_info:
            guard = r.get("guard", "")
            if neg_marker in guard:
                continue
            if _guard_contains_condition(guard, cond_norm):
                return r
        return None
    # 反向：需要 guard 显式否定该条件
    for r in returns_info:
        guard = r.get("guard", "")
        if neg_marker in guard:
            return r
    return None


def _guard_contains_condition(guard: str, cond: str) -> bool:
    """判断 guard 中是否作为独立子句包含 cond（不被 not (...) 包裹）。

    简单实现：按 ' and ' 拆分 guard 的顶层子句，检查是否有一项等于 cond。
    """
    if not guard:
        return False
    # 拆顶层 and 子句（忽略括号内的 and）
    parts = _split_top_level_and(guard)
    return cond in parts


def _split_top_level_and(expr: str) -> list[str]:
    """按顶层 `and` 拆分表达式，尊重括号嵌套。"""
    parts: list[str] = []
    depth = 0
    buf = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch == "(":
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ")":
            depth -= 1
            buf.append(ch)
            i += 1
            continue
        # 匹配顶层 " and "
        if depth == 0 and expr[i:i + 5] == " and ":
            parts.append("".join(buf).strip())
            buf = []
            i += 5
            continue
        buf.append(ch)
        i += 1
    if buf:
        parts.append("".join(buf).strip())
    return parts


def _format_return_expected(cond: str, ret: dict) -> str:
    """将一个 return 项格式化为 expected 文本。"""
    kind = ret.get("kind", "return")
    value = ret.get("value", "?")
    if kind == "raise":
        exc_type = ret.get("exception_type", "Exception")
        return f"当 {cond} 时抛出 {exc_type}（{value}）"
    return f"当 {cond} 时返回 {value}"


def _format_equivalence_expected(
    returns_info: list[dict], max_returns: int = 4
) -> str:
    """为等价类用例生成 expected 文本。

    - 无 returns_info：泛化文本
    - 只有 return：列出所有可能返回值
    - 有 raise：列出 return 值 + 异常类型
    """
    if not returns_info:
        return "正常返回，不抛出异常"

    returns = [r for r in returns_info if r.get("kind") == "return"]
    raises = [r for r in returns_info if r.get("kind") == "raise"]

    # 用 dict.fromkeys 保序去重
    return_values = list(dict.fromkeys(
        r.get("value", "?") for r in returns
    ))[:max_returns]
    exc_types = list(dict.fromkeys(
        r.get("exception_type", "Exception") for r in raises
    ))[:max_returns]

    parts: list[str] = []
    if return_values:
        if len(return_values) == 1:
            parts.append(f"预期返回 {return_values[0]}")
        else:
            parts.append(
                "预期返回值之一: " + " / ".join(return_values)
            )
    if exc_types:
        if len(exc_types) == 1:
            parts.append(f"或抛出 {exc_types[0]}")
        else:
            parts.append(
                "或抛出异常之一: " + " / ".join(exc_types)
            )
    if not parts:
        return "正常返回，不抛出异常"
    return "；".join(parts)


# ---------------------------------------------------------------------------
# 用例排序与硬性上限（借鉴 code-review 的 "≤10 findings" 模式）
# ---------------------------------------------------------------------------

# severity → 分数（用于排序）
_SEVERITY_SCORE: dict[str, int] = {
    "critical": 100,
    "high": 70,
    "medium": 40,
    "low": 15,
}

# 默认配额（每个函数）
DEFAULT_QUOTAS: dict = {
    # 一个函数最多这么多用例
    "total_max": 15,

    # 按类型的最大数量（避免某类刷屏）
    "per_type_max": {
        "equivalence_class": 1,   # 一个函数一条基础用例
        "exception_path": 1,      # 综合分支覆盖一条
        "decision_table": 5,      # 复杂条件的核心
        "boundary_value": 4,      # 挑最关键的边界
        "edge_case": 2,           # 边缘情况
        "security_test": 3,       # 挑最高危的安全测试
        "performance": 1,         # 性能一条示例
    },

    # 每种 severity 至少保留的数量（保证核心一定有）
    "min_by_severity": {
        "critical": 3,
        "high": 4,
    },
}


def _score_case(case: dict) -> int:
    """给一条 case 打综合分。分数越高优先级越高。

    当前 MVP 实现只用 severity。后续可加 coverage_value 和 confidence。
    """
    severity = case.get("severity", "medium")
    return _SEVERITY_SCORE.get(severity, 40)


def prioritize_cases(
    cases: list[dict],
    quotas: dict | None = None,
) -> list[dict]:
    """按 severity 排序并按配额筛选用例，控制每个函数的用例总数。

    筛选策略（分 3 阶段）:
        1. 保底: 每种 severity 至少保留 min_by_severity 条
        2. 补齐: 按分数从高到低，遵守 per_type_max 上限
        3. 硬上限: 总数不超过 total_max

    Args:
        cases: 单个函数产生的所有用例
        quotas: 配额配置（默认 DEFAULT_QUOTAS）

    Returns:
        筛选并排序后的用例列表
    """
    if not cases:
        return []

    quotas = quotas or DEFAULT_QUOTAS
    total_max = quotas.get("total_max", 15)
    per_type_max = quotas.get("per_type_max", {})
    min_by_severity = quotas.get("min_by_severity", {})

    # 1. 打分 + 稳定排序（分数降序）
    scored = sorted(
        cases,
        key=lambda c: (-_score_case(c), _TYPE_PRIORITY.get(c.get("type", ""), 99)),
    )

    # 2. 保底阶段：每种 severity 先塞入最少数量
    result: list[dict] = []
    type_counts: dict[str, int] = {}
    remaining = list(scored)

    for severity, min_count in min_by_severity.items():
        candidates = [c for c in remaining if c.get("severity") == severity]
        for c in candidates[:min_count]:
            if len(result) >= total_max:
                break
            t = c.get("type", "")
            if type_counts.get(t, 0) >= per_type_max.get(t, total_max):
                continue
            result.append(c)
            type_counts[t] = type_counts.get(t, 0) + 1
            remaining.remove(c)

    # 3. 补齐阶段：按分数从高到低补，遵守 per_type_max
    for c in remaining:
        if len(result) >= total_max:
            break
        t = c.get("type", "")
        if type_counts.get(t, 0) >= per_type_max.get(t, total_max):
            continue
        result.append(c)
        type_counts[t] = type_counts.get(t, 0) + 1

    # 4. 最终按 severity + type 稳定排序，让输出更可读
    result.sort(
        key=lambda c: (-_score_case(c), _TYPE_PRIORITY.get(c.get("type", ""), 99)),
    )
    return result


def _group_cases_by_target(cases: list[dict]) -> dict[str, list[dict]]:
    """按 target（函数名）分组用例。"""
    groups: dict[str, list[dict]] = {}
    for c in cases:
        target = c.get("target", "")
        groups.setdefault(target, []).append(c)
    return groups


def _count_by_severity(cases: list[dict]) -> dict[str, int]:
    """统计各 severity 的用例数量。"""
    counts: dict[str, int] = {}
    for c in cases:
        sev = c.get("severity", "unknown")
        counts[sev] = counts.get(sev, 0) + 1
    return counts

