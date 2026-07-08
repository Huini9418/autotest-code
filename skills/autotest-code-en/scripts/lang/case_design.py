"""四种用例设计共享算法：等价类 / 边界值 / 异常路径 / 决策表。

语言无关的算法逻辑，通过 ``type_boundaries`` 和 ``type_normals``
参数接收每语言独立的数据，实现算法共享、数据隔离。
"""

from typing import Any


def design_cases(
    analysis: dict,
    type_boundaries: dict,
    type_normals: dict,
) -> dict:
    """基于分析结果生成测试用例清单。

    按四种方法生成:
        - 等价类划分: 类型注解推导正常值
        - 边界值分析: type_boundaries 映射表
        - 异常路径: 分支数 > 0 时生成
        - 决策表: 分支数 >= 3 时生成

    Args:
        analysis: analyze() 的输出
        type_boundaries: 类型 -> 边界值列表
        type_normals: 类型 -> 正常值列表

    Returns:
        {"test_cases": [...], "summary": {...}}
    """
    test_cases: list[dict] = []
    files = analysis.get("files", [])

    for finfo in files:
        if "error" in finfo:
            continue
        rel = finfo.get("file", "")
        for func in finfo.get("functions", []):
            test_cases.extend(
                _gen_for_function(
                    rel, func, type_boundaries, type_normals
                )
            )
        for cls in finfo.get("classes", []):
            for method in cls.get("methods", []):
                test_cases.extend(
                    _gen_for_function(
                        rel, method, type_boundaries, type_normals
                    )
                )

    summary = {
        "total_cases": len(test_cases),
        "by_type": _count_by_type(test_cases),
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
            for part in inner.split(","):
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
    cases.append(
        {
            "target": name,
            "file": rel_file,
            "type": "equivalence_class",
            "description": f"{name} 正常输入等价类",
            "inputs": normal_inputs,
            "expected": "正常返回，不抛出异常",
        }
    )

    # 边界值分析
    boundary_cases = _build_boundary_cases(
        name, rel_file, relevant_args, type_boundaries, type_normals
    )
    cases.extend(boundary_cases)

    # 异常路径
    if branches > 0:
        cases.append(
            {
                "target": name,
                "file": rel_file,
                "type": "exception_path",
                "description": f"{name} 分支覆盖（{branches} 个分支节点）",
                "inputs": normal_inputs,
                "expected": "覆盖各分支路径，验证返回值或异常",
            }
        )

    # 决策表
    if branches >= 3:
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
            }
        )

    return cases


def _build_normal_inputs(
    args: list[dict], type_normals: dict
) -> dict[str, str]:
    """构建等价类正常输入。"""
    inputs: dict[str, str] = {}
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
                inputs[arg["name"]] = "None"
        else:
            inputs[arg["name"]] = "None"
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
                        other_type = _resolve_type(
                            other_ann, type_normals
                        )
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


def _count_by_type(cases: list[dict]) -> dict[str, int]:
    """统计用例类型分布。"""
    counts: dict[str, int] = {}
    for c in cases:
        t = c.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return counts
