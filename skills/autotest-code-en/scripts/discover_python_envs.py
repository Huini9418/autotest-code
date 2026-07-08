#!/usr/bin/env python3
"""发现系统上所有可用的 Python 环境。

按优先级检测以下来源：
    1. 项目本地 venv（从 target_path 向上找 .venv/ venv/）
    2. 当前激活的 venv（VIRTUAL_ENV 环境变量）
    3. pyenv（pyenv versions 或扫描 ~/.pyenv/versions/）
    4. conda（conda env list --json）
    5. uv（uv python list）
    6. Homebrew（/opt/homebrew/bin/python3、/usr/local/bin/python3）
    7. 系统（/usr/bin/python3、/usr/bin/python、/usr/bin/python2）

每个环境包含：路径、版本、类型、pytest 安装状态。
输出 JSON 含 environments 列表和 recommended 推荐路径。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 子进程超时（秒）
_TIMEOUT_VERSION = 10   # python --version
_TIMEOUT_PYTEST = 5     # pytest 检测
_TIMEOUT_PYENV = 10     # pyenv versions --bare
_TIMEOUT_CONDA = 15     # conda env list --json
_TIMEOUT_UV = 15        # uv python list

# 向上查找 venv 的最大目录层数
_MAX_PARENT_DEPTH = 20


def discover_python_envs(target_path: str) -> list[dict]:
    """发现系统上所有可用的 Python 环境。

    Args:
        target_path: 目标路径，用于探测项目本地 venv

    Returns:
        环境信息字典列表
    """
    envs = []
    seen_paths = set()  # 基于 realpath 去重

    # 1. 项目本地 venv
    envs.extend(_find_project_venvs(target_path, seen_paths))

    # 2. 当前激活的 venv
    envs.extend(_find_active_venv(seen_paths))

    # 3. pyenv
    envs.extend(_find_pyenv_envs(seen_paths))

    # 4. conda
    envs.extend(_find_conda_envs(seen_paths))

    # 5. uv
    envs.extend(_find_uv_envs(seen_paths))

    # 6. Homebrew + 系统
    envs.extend(_find_system_pythons(seen_paths))

    return envs


def _make_env(
    path: str,
    env_type: str,
    seen_paths: set[str],
) -> dict | None:
    """创建环境信息字典，去重并检测版本和 pytest。

    Returns:
        环境信息字典，若路径已存在或不可用则返回 None
    """
    if not path or not os.path.exists(path):
        return None

    real = os.path.realpath(path)
    if real in seen_paths:
        return None
    seen_paths.add(real)

    version_str, version_tuple, is_python2 = _get_version(path)
    if version_str is None:
        return None

    pytest_info = _check_pytest(path)

    return {
        "path": path,
        "version": version_str,
        "version_tuple": version_tuple,
        "type": env_type,
        "has_pytest": pytest_info["has_pytest"],
        "pytest_version": pytest_info["pytest_version"],
        "is_python2": is_python2,
    }


def _get_version(python_path: str) -> tuple[str | None, list[int], bool]:
    """获取 Python 版本信息。

    Returns:
        (版本字符串, 版本号列表, 是否 Python 2)
    """
    try:
        proc = subprocess.run(
            [python_path, "--version"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_VERSION,
        )
        output = (proc.stdout.strip() or proc.stderr.strip())
        if not output:
            return None, [], False
        version_str = output.split("\n")[0]
        version_tuple, is_python2 = _parse_version(version_str)
        return version_str, version_tuple, is_python2
    except (subprocess.TimeoutExpired, OSError):
        return None, [], False


def _parse_version(version_str: str) -> tuple[list[int], bool]:
    """从版本字符串解析版本号。

    >>> _parse_version("Python 3.12.0")
    ([3, 12, 0], False)
    >>> _parse_version("Python 2.7.18")
    ([2, 7, 18], True)
    """
    import re

    parts = []
    # 匹配形如 "3.12.0" 或 "3.12.0rc1" 的版本号（只取数字部分）
    m = re.search(r"\b(\d+)\.(\d+)(?:\.(\d+))?", version_str)
    if m:
        parts = [int(m.group(1)), int(m.group(2))]
        if m.group(3) is not None:
            parts.append(int(m.group(3)))
    is_python2 = len(parts) > 0 and parts[0] == 2
    return parts, is_python2


def _check_pytest(python_path: str) -> dict:
    """检查指定 Python 是否安装了 pytest。

    Returns:
        {"has_pytest": bool, "pytest_version": str | None}
    """
    try:
        result = subprocess.run(
            [python_path, "-c", "import pytest; print(pytest.__version__)"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_PYTEST,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            if version:
                return {"has_pytest": True, "pytest_version": version}
    except (subprocess.TimeoutExpired, OSError):
        pass
    return {"has_pytest": False, "pytest_version": None}


def _find_project_venvs(
    target_path: str, seen_paths: set[str]
) -> list[dict]:
    """从 target_path 向上查找项目本地 venv。"""
    envs = []
    if not target_path or not os.path.exists(target_path):
        return envs

    start = (
        target_path if os.path.isdir(target_path)
        else os.path.dirname(target_path)
    )
    if not start:
        return envs

    start = os.path.abspath(start)
    venv_names = [".venv", "venv", ".env"]
    venv_bin_names = ["python", "python3"]

    current = start
    for _ in range(_MAX_PARENT_DEPTH):
        for venv_name in venv_names:
            venv_dir = os.path.join(current, venv_name)
            bin_dir = os.path.join(venv_dir, "bin")
            if not os.path.isdir(bin_dir):
                continue
            for bin_name in venv_bin_names:
                python_path = os.path.join(bin_dir, bin_name)
                env = _make_env(python_path, "project_venv", seen_paths)
                if env:
                    envs.append(env)
                    break  # 同一 venv 只加一次
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    return envs


def _find_active_venv(seen_paths: set[str]) -> list[dict]:
    """检测 VIRTUAL_ENV 环境变量指向的 venv。"""
    envs = []
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if not virtual_env:
        return envs

    for bin_name in ["python", "python3"]:
        python_path = os.path.join(virtual_env, "bin", bin_name)
        env = _make_env(python_path, "virtualenv", seen_paths)
        if env:
            envs.append(env)
            break
    return envs


def _find_pyenv_envs(seen_paths: set[str]) -> list[dict]:
    """检测 pyenv 管理的 Python 环境。"""
    envs = []

    # 优先用 pyenv versions --bare
    pyenv_bin = shutil.which("pyenv")
    if pyenv_bin:
        try:
            proc = subprocess.run(
                [pyenv_bin, "versions", "--bare"],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_PYENV,
            )
            if proc.returncode == 0:
                for line in proc.stdout.strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    # pyenv versions --bare 输出形如 "3.12.0" 或 "3.12.0/envs/foo"
                    version_name = line.split("/")[-1]
                    python_path = os.path.expanduser(
                        f"~/.pyenv/versions/{version_name}/bin/python"
                    )
                    env = _make_env(python_path, "pyenv", seen_paths)
                    if env:
                        envs.append(env)
            return envs
        except (subprocess.TimeoutExpired, OSError):
            pass

    # fallback: 扫描 ~/.pyenv/versions/
    pyenv_versions_dir = os.path.expanduser("~/.pyenv/versions")
    if os.path.isdir(pyenv_versions_dir):
        for name in sorted(os.listdir(pyenv_versions_dir)):
            python_path = os.path.join(
                pyenv_versions_dir, name, "bin", "python"
            )
            env = _make_env(python_path, "pyenv", seen_paths)
            if env:
                envs.append(env)

    return envs


def _find_conda_envs(seen_paths: set[str]) -> list[dict]:
    """检测 conda 管理的 Python 环境。"""
    envs = []
    conda_bin = shutil.which("conda")
    if not conda_bin:
        return envs

    try:
        proc = subprocess.run(
            [conda_bin, "env", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_CONDA,
        )
        if proc.returncode != 0:
            return envs
        data = json.loads(proc.stdout)
        env_paths = data.get("envs", [])
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        return envs

    for env_path in env_paths:
        for bin_name in ["python", "python3"]:
            python_path = os.path.join(env_path, "bin", bin_name)
            env = _make_env(python_path, "conda", seen_paths)
            if env:
                envs.append(env)
                break

    return envs


def _find_uv_envs(seen_paths: set[str]) -> list[dict]:
    """检测 uv 管理的 Python 环境。"""
    envs = []
    uv_bin = shutil.which("uv")
    if not uv_bin:
        return envs

    try:
        proc = subprocess.run(
            [uv_bin, "python", "list"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_UV,
        )
        if proc.returncode != 0:
            return envs
    except (subprocess.TimeoutExpired, OSError):
        return envs

    # uv python list 输出形如：
    # cpython-3.12.0-macos-aarch64-none    /Users/foo/.local/share/uv/python/...
    for line in proc.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        python_path = parts[-1]
        # 确保是 python 可执行文件
        if not python_path.endswith("python") and not python_path.endswith(
            "python3"
        ):
            python_path = os.path.join(python_path, "bin", "python")
        env = _make_env(python_path, "uv", seen_paths)
        if env:
            envs.append(env)

    return envs


def _find_system_pythons(seen_paths: set[str]) -> list[dict]:
    """检测 Homebrew 和系统 Python。"""
    envs = []

    # Homebrew (Apple Silicon + Intel)
    homebrew_paths = [
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
    ]
    for path in homebrew_paths:
        env = _make_env(path, "homebrew", seen_paths)
        if env:
            envs.append(env)

    # 系统 Python
    system_paths = [
        "/usr/bin/python3",
        "/usr/bin/python",
        "/usr/bin/python2",
    ]
    for path in system_paths:
        env = _make_env(path, "system", seen_paths)
        if env:
            envs.append(env)

    return envs


def recommend_environment(envs: list[dict]) -> str | None:
    """推荐最合适的 Python 环境。

    优先级：
        1. project_venv 且有 pytest
        2. virtualenv 且有 pytest
        3. 任何 has_pytest=true 的 Python 3 环境
        4. 第一个 Python 3 环境
    """
    if not envs:
        return None

    # 1. project_venv + pytest
    for env in envs:
        if (
            env["type"] == "project_venv"
            and env["has_pytest"]
            and not env["is_python2"]
        ):
            return env["path"]

    # 2. virtualenv + pytest
    for env in envs:
        if (
            env["type"] == "virtualenv"
            and env["has_pytest"]
            and not env["is_python2"]
        ):
            return env["path"]

    # 3. 任何有 pytest 的 Python 3
    for env in envs:
        if env["has_pytest"] and not env["is_python2"]:
            return env["path"]

    # 4. 第一个 Python 3
    for env in envs:
        if not env["is_python2"]:
            return env["path"]

    return envs[0]["path"]


def main():
    parser = argparse.ArgumentParser(
        description="发现系统上所有可用的 Python 环境"
    )
    parser.add_argument(
        "target_path",
        help="目标路径（用于探测项目本地 venv）",
    )
    parser.add_argument(
        "--output",
        help="输出 JSON 文件路径（可选，默认 stdout）",
    )
    args = parser.parse_args()

    envs = discover_python_envs(args.target_path)
    recommended = recommend_environment(envs)
    result = {
        "environments": envs,
        "recommended": recommended,
    }
    output = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        out_path = Path(os.path.expanduser(args.output))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(
            f"Found {len(envs)} Python environment(s), "
            f"written to {out_path}",
            file=sys.stderr,
        )
    else:
        print(output)


if __name__ == "__main__":
    main()
