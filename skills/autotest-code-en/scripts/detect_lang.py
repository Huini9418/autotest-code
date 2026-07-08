#!/usr/bin/env python3
"""语言 + 框架 + 工具链检测。

借鉴 test-orchestrator 的 detect_lang.py 模式：
- 文件扩展名 -> 语言
- 项目配置文件 -> 语言 + 测试框架
- 运行时工具链检查 -> 缺失时提示安装
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 文件扩展名 -> 语言
EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}

# 项目配置文件 -> 语言
CONFIG_FILE_MAP: dict[str, str] = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "requirements.txt": "python",
    "package.json": "javascript",
    "tsconfig.json": "typescript",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "pom.xml": "java",
    "build.gradle": "java",
}

# tree-sitter 依赖包名
TREE_SITTER_PACKAGES: dict[str, str] = {
    "javascript": "tree-sitter-javascript",
    "typescript": "tree-sitter-typescript",
    "go": "tree-sitter-go",
    "rust": "tree-sitter-rust",
    "java": "tree-sitter-java",
}

# 工具链检查命令（语言基础工具）
TOOLCHAIN_CHECKS: dict[str, list[str]] = {
    "python": ["python3", "--version"],
    "javascript": ["node", "--version"],
    "typescript": ["node", "--version"],
    "go": ["go", "version"],
    "rust": ["rustc", "--version"],
    "java": ["java", "-version"],
}

# 测试命令实际用到的工具（补充检查，TOOLCHAIN_CHECKS 之外的工具）
TEST_CMD_TOOLS: dict[str, list[str]] = {
    "python": ["pytest"],
    "javascript": [],
    "typescript": [],
    "go": ["gotestsum"],
    "rust": ["cargo", "cargo-nextest"],
    "java": ["mvn"],
}

# 测试框架检查
TEST_FRAMEWORK_CHECKS: dict[str, dict] = {
    "python": {
        "files": ["pytest.ini", "pyproject.toml", "setup.cfg"],
        "deps_file": "requirements.txt",
        "dep_check": "pytest",
    },
    "javascript": {
        "files": ["jest.config.js", "jest.config.ts", "vitest.config.ts"],
        "deps_file": "package.json",
        "dep_checks": {
            "jest": "jest",
            "vitest": "vitest",
        },
    },
    "typescript": {
        "files": ["jest.config.ts", "vitest.config.ts"],
        "deps_file": "package.json",
        "dep_checks": {
            "jest": "jest",
            "vitest": "vitest",
        },
    },
    "go": {
        "files": ["go.mod"],
        "deps_file": None,
        "dep_check": "gotestsum",
    },
    "rust": {
        "files": ["Cargo.toml"],
        "deps_file": None,
        "dep_check": "cargo",
    },
    "java": {
        "files": ["pom.xml", "build.gradle"],
        "deps_file": None,
        "dep_check": "mvn",
    },
}


def detect_language(target_path: str) -> str:
    """检测目标路径的编程语言。

    优先级：
        1. 文件扩展名直接映射
        2. 项目配置文件映射
        3. 默认 python
    """
    if os.path.isfile(target_path):
        ext = os.path.splitext(target_path)[1].lower()
        if ext in EXTENSION_MAP:
            return EXTENSION_MAP[ext]

    # 检查目录下的配置文件
    check_dir = (
        target_path if os.path.isdir(target_path)
        else os.path.dirname(target_path)
    )
    if check_dir and os.path.isdir(check_dir):
        for config_file, lang in CONFIG_FILE_MAP.items():
            if os.path.exists(os.path.join(check_dir, config_file)):
                # package.json 可能是 JS 或 TS
                if config_file == "package.json":
                    ts_config = os.path.join(check_dir, "tsconfig.json")
                    if os.path.exists(ts_config):
                        return "typescript"
                return lang

    return "python"


def detect_framework(target_path: str, lang: str) -> str:
    """检测测试框架。"""
    check_dir = (
        target_path if os.path.isdir(target_path)
        else os.path.dirname(target_path)
    )
    if not check_dir or not os.path.isdir(check_dir):
        return _default_framework(lang)

    fw_config = TEST_FRAMEWORK_CHECKS.get(lang, {})

    # 检查框架配置文件
    for fw_file in fw_config.get("files", []):
        if os.path.exists(os.path.join(check_dir, fw_file)):
            if "vitest" in fw_file:
                return "vitest"
            if "jest" in fw_file:
                return "jest"
            # Java: pom.xml → maven, build.gradle → gradle
            if fw_file == "pom.xml":
                return "maven"
            if fw_file == "build.gradle":
                return "gradle"

    # 检查依赖文件
    deps_file = fw_config.get("deps_file")
    if deps_file:
        deps_path = os.path.join(check_dir, deps_file)
        if os.path.exists(deps_path):
            content = Path(deps_path).read_text(encoding="utf-8")
            dep_checks = fw_config.get("dep_checks", {})
            if isinstance(dep_checks, dict):
                for dep, framework in dep_checks.items():
                    if dep in content:
                        return framework
            elif fw_config.get("dep_check"):
                if fw_config["dep_check"] in content:
                    return fw_config["dep_check"]

    return _default_framework(lang)


def _default_framework(lang: str) -> str:
    defaults = {
        "python": "pytest",
        "javascript": "jest",
        "typescript": "jest",
        "go": "gotestsum",
        "rust": "cargo nextest",
        "java": "maven",
    }
    return defaults.get(lang, "unknown")


def check_toolchain(lang: str, python_path: str | None = None) -> dict:
    """检查语言工具链是否可用。

    检查两部分：
        1. 语言基础工具（TOOLCHAIN_CHECKS）
        2. 测试命令实际用到的工具（TEST_CMD_TOOLS）

    Args:
        lang: 目标语言
        python_path: 指定的 Python 解释器路径（仅 Python）。
            指定时用它替代 shutil.which("python3")，并用
            ``python -m pytest --version`` 检查 pytest。

    Returns:
        {"available": bool, "tool": str, "version": str, "missing": list,
         "python_path": str | None}
    """
    result = {
        "available": True,
        "tool": lang,
        "version": "",
        "missing": [],
        "python_path": python_path if lang == "python" else None,
    }

    # Python 指定 python_path 时走独立分支
    if lang == "python" and python_path:
        return _check_python_toolchain_with_path(python_path, result)

    cmd_parts = TOOLCHAIN_CHECKS.get(lang, [])
    all_tools = list(cmd_parts[:1])  # 基础工具的可执行文件
    # 补充测试命令用到的工具
    all_tools.extend(TEST_CMD_TOOLS.get(lang, []))

    for tool in all_tools:
        if not shutil.which(tool):
            result["available"] = False
            result["missing"].append(tool)

    # 获取基础工具版本
    if cmd_parts:
        executable = cmd_parts[0]
        args = cmd_parts[1:]
        if shutil.which(executable):
            try:
                proc = subprocess.run(
                    [executable] + args,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                output = (
                    proc.stdout.strip()
                    or proc.stderr.strip()
                )
                result["version"] = output.split("\n")[0]
            except subprocess.TimeoutExpired:
                # 超时不算可用
                result["available"] = False
                if executable not in result["missing"]:
                    result["missing"].append(executable)
            except OSError:
                pass

    return result


def _check_python_toolchain_with_path(
    python_path: str, result: dict
) -> dict:
    """用指定的 Python 路径检查工具链。"""
    # 检查 python_path 是否存在
    if not os.path.exists(python_path):
        result["available"] = False
        result["missing"].append(python_path)
        return result

    # 获取版本
    try:
        proc = subprocess.run(
            [python_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = proc.stdout.strip() or proc.stderr.strip()
        result["version"] = output.split("\n")[0] if output else ""
    except (subprocess.TimeoutExpired, OSError) as e:
        result["available"] = False
        if isinstance(e, subprocess.TimeoutExpired):
            result["missing"].append(python_path)
        return result

    # 检查 pytest：python -m pytest --version
    try:
        proc = subprocess.run(
            [python_path, "-m", "pytest", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            result["available"] = False
            result["missing"].append("pytest")
    except subprocess.TimeoutExpired:
        result["available"] = False
        result["missing"].append("pytest")
    except OSError:
        result["available"] = False
        result["missing"].append("pytest")

    return result


def check_tree_sitter_dep(lang: str) -> dict:
    """检查 tree-sitter 依赖是否可用（Python 不需要）。

    Returns:
        {"needed": bool, "available": bool, "package": str, "hint": str}
    """
    if lang == "python":
        return {
            "needed": False,
            "available": True,
            "package": "",
            "hint": "",
        }

    pkg = TREE_SITTER_PACKAGES.get(lang, "")
    if not pkg:
        return {
            "needed": False,
            "available": True,
            "package": "",
            "hint": "",
        }

    # 尝试 import
    module_name = pkg.replace("-", "_")
    available = importlib.util.find_spec(module_name) is not None
    return {
        "needed": True,
        "available": available,
        "package": pkg,
        "hint": "" if available else f"请运行: pip install {pkg}",
    }


def check_pytest_plugins(
    target_path: str, python_path: str | None = None
) -> dict:
    """检测 pytest 插件可用性，遍历 registry.PYTEST_PLUGINS。

    Args:
        target_path: 目标路径，用于定位配置文件
        python_path: 指定 Python 解释器路径时，通过 subprocess 在
            目标环境中检测插件可用性（跨环境检测）。

    Returns:
        {"plugins": dict, "asyncio_mode": str, "pytest_asyncio": bool,
         "anyio": bool, "missing": list, "hints": list, "hint": str}
    """
    # 计算检查目录
    check_dir = (
        target_path if os.path.isdir(target_path)
        else os.path.dirname(target_path)
    )
    if not check_dir or not os.path.isdir(check_dir):
        return {
            "plugins": {},
            "asyncio_mode": "",
            "pytest_asyncio": False,
            "anyio": False,
            "missing": [],
            "hints": [],
            "hint": "",
        }

    # 扫描 asyncio_mode 配置
    asyncio_mode = _scan_asyncio_mode(check_dir)

    # 指定 python_path 时，跨环境检测插件
    if python_path:
        plugins = _check_pytest_plugins_in_env(python_path)
    else:
        from lang.registry import PYTEST_PLUGINS

        plugins = {}
        for pkg_name, info in PYTEST_PLUGINS.items():
            available = importlib.util.find_spec(info["import_name"]) is not None
            plugins[pkg_name] = {
                "available": available,
                "import_name": info["import_name"],
                "trigger_type": info["trigger_type"],
                "trigger": info["trigger"],
                "alt": info["alt"],
            }

    # 向后兼容字段
    pytest_asyncio = plugins.get("pytest-asyncio", {}).get("available", False)
    anyio = plugins.get("anyio", {}).get("available", False)

    # missing 逻辑：仅 asyncio_mode 配置时才报告必需
    missing = []
    hints = []
    if asyncio_mode and not pytest_asyncio and not anyio:
        missing.append("pytest-asyncio")
        hints.append("请运行: pip install pytest-asyncio")
    elif asyncio_mode and not pytest_asyncio:
        missing.append("pytest-asyncio")
        hints.append(
            "项目使用 anyio 但未装 pytest-asyncio，"
            "请 pip install pytest-asyncio 或改用 @pytest.mark.anyio"
        )

    return {
        "plugins": plugins,
        "asyncio_mode": asyncio_mode,
        "pytest_asyncio": pytest_asyncio,
        "anyio": anyio,
        "missing": missing,
        "hints": hints,
        "hint": "; ".join(hints) if hints else "",
    }


def _check_pytest_plugins_in_env(python_path: str) -> dict:
    """在指定 Python 环境中检测 pytest 插件可用性。

    通过 subprocess 运行检测脚本，避免当前进程 sys.path 干扰。
    """
    from lang.registry import PYTEST_PLUGINS

    plugins_repr = repr(
        {k: v["import_name"] for k, v in PYTEST_PLUGINS.items()}
    )
    script = (
        "import json, importlib.util\n"
        f"plugins = {plugins_repr}\n"
        "result = {}\n"
        "for pkg, import_name in plugins.items():\n"
        "    result[pkg] = importlib.util.find_spec(import_name) is not None\n"
        "print(json.dumps(result))\n"
    )
    try:
        proc = subprocess.run(
            [python_path, "-c", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            # 环境不可用，全部标记为不可用
            return _empty_plugins(PYTEST_PLUGINS)
        availability = json.loads(proc.stdout.strip())
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        return _empty_plugins(PYTEST_PLUGINS)

    plugins = {}
    for pkg_name, info in PYTEST_PLUGINS.items():
        plugins[pkg_name] = {
            "available": availability.get(pkg_name, False),
            "import_name": info["import_name"],
            "trigger_type": info["trigger_type"],
            "trigger": info["trigger"],
            "alt": info["alt"],
        }
    return plugins


def _empty_plugins(pytest_plugins: dict) -> dict:
    """生成全不可用的插件字典（环境不可用时用）。"""
    plugins = {}
    for pkg_name, info in pytest_plugins.items():
        plugins[pkg_name] = {
            "available": False,
            "import_name": info["import_name"],
            "trigger_type": info["trigger_type"],
            "trigger": info["trigger"],
            "alt": info["alt"],
        }
    return plugins


def detect_pytest_async_config(
    target_path: str, python_path: str | None = None
) -> dict:
    """废弃别名，调用 check_pytest_plugins() 并提取异步相关字段。"""
    result = check_pytest_plugins(target_path, python_path)
    return {
        "asyncio_mode": result["asyncio_mode"],
        "pytest_asyncio": result["pytest_asyncio"],
        "anyio": result["anyio"],
        "missing": result["missing"],
        "hint": result["hint"],
    }


def _scan_asyncio_mode(check_dir: str) -> str:
    """扫描 pytest 配置文件中的 asyncio_mode 设置。

    检查 pyproject.toml [tool.pytest.ini_options]、
    pytest.ini [pytest]、setup.cfg [tool:pytest] 三处。
    """
    # pyproject.toml
    pyproject = os.path.join(check_dir, "pyproject.toml")
    if os.path.exists(pyproject):
        mode = _scan_asyncio_from_pyproject(pyproject)
        if mode:
            return mode

    # pytest.ini
    pytest_ini = os.path.join(check_dir, "pytest.ini")
    if os.path.exists(pytest_ini):
        mode = _scan_asyncio_from_ini(pytest_ini, "pytest")
        if mode:
            return mode

    # setup.cfg
    setup_cfg = os.path.join(check_dir, "setup.cfg")
    if os.path.exists(setup_cfg):
        mode = _scan_asyncio_from_ini(setup_cfg, "tool:pytest")
        if mode:
            return mode

    return ""


def _scan_asyncio_from_pyproject(path: str) -> str:
    """从 pyproject.toml 提取 asyncio_mode。"""
    try:
        import tomllib  # Python 3.11+
        with open(path, "rb") as f:
            data = tomllib.load(f)
        opts = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
        mode = opts.get("asyncio_mode", "")
        if mode:
            return str(mode)
    except ImportError:
        # Python 3.10- 用文本扫描
        pass
    except Exception:
        pass

    # 文本扫描 fallback
    try:
        content = Path(path).read_text(encoding="utf-8")
        in_section = False
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped == "[tool.pytest.ini_options]":
                in_section = True
                continue
            if stripped.startswith("[") and in_section:
                in_section = False
            if in_section and "asyncio_mode" in stripped and "=" in stripped:
                value = stripped.split("=", 1)[1].strip()
                # 去掉引号
                value = value.strip("\"'")
                if value:
                    return value
    except Exception:
        pass

    return ""


def _scan_asyncio_from_ini(path: str, section: str) -> str:
    """从 INI 格式文件（pytest.ini / setup.cfg）提取 asyncio_mode。"""
    try:
        content = Path(path).read_text(encoding="utf-8")
        in_section = False
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped == f"[{section}]":
                in_section = True
                continue
            if stripped.startswith("[") and in_section:
                in_section = False
            if in_section and "asyncio_mode" in stripped and "=" in stripped:
                value = stripped.split("=", 1)[1].strip()
                value = value.strip("\"'")
                if value:
                    return value
    except Exception:
        pass

    return ""


def detect_all(
    target_path: str, python_path: str | None = None
) -> dict:
    """完整检测：语言 + 框架 + 工具链 + tree-sitter 依赖 + pytest 插件。

    Args:
        target_path: 目标路径
        python_path: 指定 Python 解释器路径（仅 Python 项目），
            用于跨环境检测工具链和 pytest 插件。
    """
    lang = detect_language(target_path)
    framework = detect_framework(target_path, lang)
    toolchain = check_toolchain(lang, python_path)
    tree_sitter = check_tree_sitter_dep(lang)

    # Python 额外检测 pytest 插件
    pytest_plugins = None
    if lang == "python":
        pytest_plugins = check_pytest_plugins(target_path, python_path)
        # 如果异步插件缺失，合并到 toolchain.missing
        if pytest_plugins.get("missing"):
            toolchain["available"] = False
            toolchain["missing"].extend(pytest_plugins["missing"])

    return {
        "language": lang,
        "framework": framework,
        "toolchain": toolchain,
        "tree_sitter": tree_sitter,
        "pytest_plugins": pytest_plugins,
        "target_path": target_path,
    }


def main():
    parser = argparse.ArgumentParser(
        description="检测目标路径的语言、框架和工具链"
    )
    parser.add_argument(
        "target_path",
        help="要检测的文件或目录路径",
    )
    parser.add_argument(
        "--python",
        help="指定 Python 解释器路径（用于多环境场景）",
    )
    parser.add_argument(
        "--output",
        help="输出 JSON 文件路径（可选，默认 stdout）",
    )
    args = parser.parse_args()

    if not os.path.exists(args.target_path):
        print(
            f"Error: target path not found: {args.target_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    result = detect_all(args.target_path, args.python)
    output = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        out_path = Path(os.path.expanduser(args.output))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Detection written to {out_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
