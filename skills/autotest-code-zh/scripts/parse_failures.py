#!/usr/bin/env python3
"""失败解析：JUnit XML 统一解析 + 按语言加载失败规则 + build_error。

处理 JUnit XML 方言差异（pytest / Surefire / gotestsum / jest-junit）。
编译型语言构建失败归为 build_error severity，区分编译错误与测试逻辑错误。
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

# 确保 lang 包可被导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lang import get_failure_rules, get_build_error_rules, get_pytest_plugins  # noqa: E402

# 导入临时目录工具
try:
    from utils.temp_dir import is_safe_path
except ImportError:
    # 向后兼容：如果 utils 模块不存在，提供简单实现
    def is_safe_path(path: str | Path) -> bool:
        try:
            resolved = Path(os.path.expanduser(str(path))).resolve()
            temp_dirs = [
                Path(tempfile.gettempdir()).resolve(),
                Path("/tmp").resolve(),
                Path("/var/tmp").resolve(),
            ]
            for temp_dir in temp_dirs:
                try:
                    if resolved.is_relative_to(temp_dir):
                        return True
                except ValueError:
                    pass
            try:
                user_home = Path.home().resolve()
                if resolved.is_relative_to(user_home):
                    relative_parts = resolved.relative_to(user_home).parts
                    if relative_parts:
                        first_part = relative_parts[0]
                        allowed_dirs = {".claude", ".qwenpaw", ".opencode", ".codex"}
                        if first_part in allowed_dirs:
                            return True
            except RuntimeError:
                pass
        except (OSError, RuntimeError):
            pass
        return False

# 通用失败规则（所有语言共用，在语言规则之前匹配）
COMMON_FAILURE_RULES: list[tuple[str, str, str]] = [
    (r"TimeoutError|timed out|deadline", "timeout", "test_env"),
    (r"FileNotFoundError|FileExistsError|PermissionError|ENOENT",
     "file_error", "test_env"),
]


def classify_failure(
    message: str,
    lang_rules: list[tuple[str, str, str]],
) -> tuple[str, str]:
    """根据失败消息分类，返回 (category, severity)。

    匹配优先级：
        1. build_error 规则（编译型语言构建失败）
        2. 语言特定规则
        3. 通用规则
    """
    if not message:
        return ("unknown", "test_logic")

    # 1. build_error 规则
    for pattern, category in get_build_error_rules():
        if re.search(pattern, message, re.IGNORECASE):
            return (category, "build_error")

    # 2. 语言特定规则
    for pattern, category, severity in lang_rules:
        if re.search(pattern, message, re.IGNORECASE):
            return (category, severity)

    # 3. 通用规则
    for pattern, category, severity in COMMON_FAILURE_RULES:
        if re.search(pattern, message, re.IGNORECASE):
            return (category, severity)

    return ("unknown", "test_logic")


def parse_junitxml(xml_path: str, lang: str = "python") -> dict:
    """解析 JUnit XML，处理方言差异。

    支持的方言：
        - pytest: <testcase> with <failure>/<error>/<skipped>
        - Surefire (Maven): 同上，system-out/system-err 子元素
        - gotestsum: 同上，testcase name 含 Go 测试函数名
        - jest-junit: 同上，classname 含文件路径

    Args:
        xml_path: JUnit XML 文件路径
        lang: 目标语言，用于加载失败分类规则
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    total = 0
    passed = 0
    failures: list[dict] = []
    all_cases: list[dict] = []
    errors = 0
    skipped = 0
    build_errors = 0

    lang_rules = get_failure_rules(lang)

    for testcase in root.iter("testcase"):
        total += 1
        classname = testcase.get("classname", "")
        name = testcase.get("name", "")
        # 处理 time 为空字符串或非数值的情况
        time_str = testcase.get("time", "0") or "0"
        try:
            time = float(time_str)
        except (ValueError, TypeError):
            time = 0.0

        failure_elem = testcase.find("failure")
        error_elem = testcase.find("error")
        skipped_elem = testcase.find("skipped")

        # 收集所有可能的失败消息来源（方言处理）
        # pytest: failure.message + failure.text
        # Surefire: system-out/system-err 子元素
        # gotestsum: failure.text
        # jest-junit: failure.message
        case_info = {
            "classname": classname,
            "name": name,
            "time": time,
            "status": "passed",
        }

        if failure_elem is not None or error_elem is not None:
            elem = failure_elem if failure_elem is not None else error_elem
            message = elem.get("message", "") or ""
            text = elem.text or ""

            # Surefire 方言：检查 system-out/system-err
            system_out = testcase.find("system-out")
            system_err = testcase.find("system-err")
            if system_out is not None and system_out.text:
                text = f"{text}\n{system_out.text}"
            if system_err is not None and system_err.text:
                text = f"{text}\n{system_err.text}"

            full = f"{message}\n{text}".strip()
            category, severity = classify_failure(full, lang_rules)

            status = "failed" if failure_elem is not None else "error"
            if failure_elem is not None:
                pass  # status already "failed"
            else:
                errors += 1
                status = "error"

            if severity == "build_error":
                build_errors += 1

            case_info["status"] = status
            case_info["category"] = category
            case_info["severity"] = severity
            case_info["message"] = message
            case_info["traceback"] = text[:2000]
            failures.append(
                {
                    "classname": classname,
                    "name": name,
                    "status": status,
                    "category": category,
                    "severity": severity,
                    "message": message,
                    "traceback": text[:2000],
                    "suggestion": _suggest(category, severity, full, lang),
                }
            )
        elif skipped_elem is not None:
            skipped += 1
            case_info["status"] = "skipped"
            case_info["reason"] = skipped_elem.get("message", "")
        else:
            passed += 1

        all_cases.append(case_info)

    pass_rate = (passed / total * 100) if total > 0 else 0.0

    return {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": len(failures) - errors,
            "errors": errors,
            "skipped": skipped,
            "build_errors": build_errors,
            "pass_rate": round(pass_rate, 1),
        },
        "failures": failures,
        "all_cases": all_cases,
    }


def _extract_missing_module(message: str, lang: str) -> str:
    """从失败消息中提取缺失的模块名。返回空字符串表示无法提取。"""
    if lang == "python":
        m = re.search(r"No module named ['\"](\w+)['\"]", message)
        if not m:
            m = re.search(
                r"cannot import name ['\"]\w+['\"] from ['\"](\w+)['\"]",
                message,
            )
        return m.group(1) if m else ""
    elif lang in ("javascript", "typescript"):
        m = re.search(r"Cannot find module ['\"]([^'\"]+)['\"]", message)
        if m:
            mod = m.group(1)
            if mod.startswith(".") or not mod[0].isalpha():
                return ""
            return mod
        return ""
    elif lang == "go":
        m = re.search(r"cannot find package \"([^\"]+)\"", message)
        return m.group(1) if m else ""
    elif lang == "rust":
        m = re.search(r"unresolved import (\S+)", message)
        if m:
            return m.group(1).split("::")[0]
        return ""
    elif lang == "java":
        # 类名不是依赖名，返回空由 _get_install_command 给通用提示
        return ""
    return ""


def _get_install_command(lang: str, mod_name: str) -> str:
    """返回语言对应的安装命令。mod_name 为空时返回通用提示。"""
    commands = {
        "python": f"pip install {mod_name}" if mod_name else "pip install <缺失的包>",
        "javascript": f"npm install {mod_name}" if mod_name else "npm install <缺失的包>",
        "typescript": f"npm install {mod_name}" if mod_name else "npm install <缺失的包>",
        "go": f"go get {mod_name}" if mod_name else "go get <缺失的包>",
        "rust": f"cargo add {mod_name}" if mod_name else "cargo add <缺失的 crate>",
        "java": "在 pom.xml/build.gradle 中添加缺失的依赖",
    }
    return commands.get(
        lang, f"安装缺失的依赖: {mod_name}" if mod_name else "安装缺失的依赖"
    )


def _suggest(
    category: str, severity: str, message: str = "", lang: str = "python"
) -> str:
    """根据失败分类给出修复建议。"""
    # missing_plugin: 从 PYTEST_PLUGINS 查找具体安装建议
    if category == "missing_plugin" and message:
        for pkg_name, info in get_pytest_plugins().items():
            if re.search(info["error_pattern"], message, re.IGNORECASE):
                return (
                    f"🔧 缺少 {pkg_name}。请运行: pip install {pkg_name}，"
                    f"或{info['alt']}"
                )

    # import_error: 多语言缺失模块提取 + 安装命令
    if category == "import_error" and message:
        mod = _extract_missing_module(message, lang)
        if mod or lang in (
            "python", "javascript", "typescript", "go", "rust", "java",
        ):
            cmd = _get_install_command(lang, mod)
            return f"🔧 缺失依赖。请运行: {cmd}，或检查 import 路径"

    suggestions = {
        "assertion_error": (
            "检查测试预期值是否正确，或源码逻辑是否有 "
            "off-by-one 等错误"
        ),
        "import_error": (
            "检查依赖是否安装、import 路径是否正确、"
            "sys.path 配置"
        ),
        "missing_plugin": (
            "测试依赖的 pytest 插件未安装，安装插件或使用替代方案"
        ),
        "type_error": "检查参数类型、函数签名、是否传入了 None",
        "value_error": "检查输入值范围，添加参数校验或调整测试输入",
        "key_error": "检查字典 key 是否存在，或 fixture 数据是否完整",
        "attribute_error": (
            "检查对象是否有该属性，是否 mock 了不存在的属性"
        ),
        "file_error": (
            "检查测试文件路径、临时目录权限、conftest 配置"
        ),
        "fixture_error": "检查 conftest.py 中 fixture 定义和作用域",
        "collection_error": (
            "检查测试文件语法、import 错误、conftest 问题"
        ),
        "timeout": "检查死循环、网络超时、或增加 timeout 配置",
        "syntax_error": "修复测试文件语法错误",
        "name_error": "检查变量名拼写、是否遗漏 import",
        "runtime_error": "疑似源码 bug，检查运行时逻辑",
        "zero_division": "疑似源码 bug，检查除零保护",
        "index_error": "疑似源码 bug，检查索引边界",
        "stop_iteration": "疑似源码 bug，检查迭代器逻辑",
        "reference_error": "检查变量是否已声明、作用域是否正确",
        "network_error": "检查网络连接、mock 外部 API 调用",
        "json_error": "检查 JSON 格式是否正确",
        "type_mismatch": "检查 TypeScript 类型是否匹配",
        "property_error": "检查对象属性是否存在",
        "panic": "疑似源码 bug，检查 panic 原因",
        "nil_pointer": "疑似源码 bug，检查 nil 指针解引用",
        "goroutine_error": "疑似源码 bug，检查 goroutine 并发逻辑",
        "unwrap_none": "疑似源码 bug，检查 Option::unwrap 调用",
        "unwrap_err": "疑似源码 bug，检查 Result::unwrap 调用",
        "lifetime_error": "检查 Rust 生命周期标注",
        "null_pointer": "疑似源码 bug，检查 null 引用",
        "class_not_found": "检查依赖是否安装、类路径配置",
        "illegal_argument": "检查参数合法性",
        "io_error": "检查 IO 操作、文件权限",
        "stack_overflow": "疑似源码 bug，检查递归终止条件",
        "no_such_element": "疑似源码 bug，检查集合访问",
        "class_cast": "检查类型转换是否安全",
        "out_of_memory": "检查内存使用，增加 JVM 堆大小",
        "compilation_error": (
            "编译失败：检查语法错误、类型不匹配、"
            "缺失依赖"
        ),
        "syntax_build_error": "编译语法错误：检查代码语法",
        "unresolved_dependency": (
            "未解析的依赖：检查 import/require 是否正确"
        ),
        "rust_compile_error": "Rust 编译错误：检查类型和生命周期",
        "java_compile_error": "Java 编译错误：检查语法和类型",
        "ts_compile_error": "TypeScript 编译错误：检查类型",
        "range_error": "疑似源码 bug，检查递归或数组边界",
        "unknown": "根据 traceback 详细分析",
    }
    base = suggestions.get(category, suggestions["unknown"])
    if severity == "build_error":
        return (
            f"🔨 {base}。编译失败，修复后重新构建。"
        )
    if severity == "target_bug":
        return f"⚠️ {base}。不要修改源码，报告给用户确认。"
    if severity == "test_setup":
        return f"🔧 {base}。修复测试环境/配置。"
    if severity == "test_env":
        return f"🌐 {base}。检查运行环境。"
    return f"📝 {base}。修复测试代码。"


_HISTORY_MAX_ENTRIES = 10


def _compute_failure_signature(failures: list[dict]) -> dict:
    """计算失败签名。

    签名 = (failure_count, sorted_failing_test_names, sorted_category_set) 的哈希。
    修了一个测试后 count 变化，签名也变化，不会误触发 stop。

    Returns:
        {"signature": str, "count": int, "test_names": list}
    """
    if not failures:
        return {"signature": "", "count": 0, "test_names": []}

    count = len(failures)
    test_names = sorted(
        f"{f.get('classname', '')}::{f.get('name', '')}" for f in failures
    )
    categories = sorted(set(f.get("category", "unknown") for f in failures))

    sig_input = f"{count}|{','.join(test_names)}|{','.join(categories)}"
    signature = hashlib.md5(sig_input.encode()).hexdigest()[:8]

    return {"signature": signature, "count": count, "test_names": test_names}


def _validate_history_path(path: str) -> str:
    """验证 history file 路径必须在 tmp 或特定平台目录下。"""
    resolved = Path(os.path.expanduser(path)).resolve()

    if not is_safe_path(resolved):
        raise ValueError(
            f"history file must be under a temp directory, skill temp directory, "
            f"or one of: ~/.claude, ~/.qwenpaw, ~/.opencode, ~/.codex, got: {resolved}"
        )
    return str(resolved)


def _load_history(history_path: str, already_validated: bool = False) -> list[dict]:
    """加载历史失败签名。路径不存在时返回空列表。"""
    try:
        if already_validated:
            validated = history_path
        else:
            validated = _validate_history_path(history_path)
        if os.path.exists(validated):
            return json.loads(Path(validated).read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError, OSError):
        pass
    return []


def _append_history(history_path: str, sig_info: dict) -> list[dict]:
    """追加签名到历史文件，返回更新后的历史列表。上限 10 条。"""
    try:
        validated = _validate_history_path(history_path)
        history = _load_history(validated, already_validated=True)
        history.append(
            {
                "signature": sig_info["signature"],
                "count": sig_info["count"],
                "test_names": sig_info["test_names"],
                "timestamp": datetime.now().isoformat(),
            }
        )
        history = history[-_HISTORY_MAX_ENTRIES:]
        Path(validated).parent.mkdir(parents=True, exist_ok=True)
        Path(validated).write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return history
    except (ValueError, OSError):
        return []


def main():
    parser = argparse.ArgumentParser(
        description="解析 JUnit XML 输出，分类失败原因（多语言支持）"
    )
    parser.add_argument(
        "--junitxml",
        required=True,
        help="JUnit XML 文件路径",
    )
    parser.add_argument(
        "--lang",
        default="python",
        help="目标语言（默认 python），用于加载失败分类规则",
    )
    parser.add_argument(
        "--output",
        help="输出 JSON 文件路径（可选，默认 stdout）",
    )
    parser.add_argument(
        "--history-file",
        help="失败签名历史文件路径（用于跨调用重复检测）",
    )
    args = parser.parse_args()

    xml_path = Path(args.junitxml)
    if not xml_path.exists():
        print(
            f"Error: junitxml file not found: {xml_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    result = parse_junitxml(str(xml_path), args.lang)

    # 失败重复追踪
    history_file = os.path.expanduser(args.history_file) if args.history_file else None
    if history_file:
        failures = result.get("failures", [])
        if failures:
            sig_info = _compute_failure_signature(failures)
            history = _append_history(history_file, sig_info)
            # 统计相同签名出现次数
            current_sig = sig_info["signature"]
            repeat_count = sum(
                1 for h in history if h.get("signature") == current_sig
            )
            result["stop"] = repeat_count >= 2
            result["repeat_count"] = repeat_count
        else:
            # 全部通过，清空历史文件
            try:
                validated = _validate_history_path(history_file)
                if os.path.exists(validated):
                    Path(validated).write_text("[]", encoding="utf-8")
            except (ValueError, OSError):
                pass
            result["stop"] = False
            result["repeat_count"] = 0
    else:
        result["stop"] = False

    output = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        out_path = Path(os.path.expanduser(args.output))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Report written to {out_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
