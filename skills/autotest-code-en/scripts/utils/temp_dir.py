"""
临时文件目录管理工具。

提供跨平台的临时文件路径管理，支持：
- 系统临时目录（推荐）：{tempdir}/.claude-skills/autotest-code/
- 向后兼容的平台目录：~/.claude/, ~/.qwenpaw/, ~/.opencode/, ~/.codex/
"""

import os
import tempfile
from pathlib import Path
from typing import Optional


# 允许的平台目录（向后兼容）
_ALLOWED_PLATFORM_DIRS = {".claude", ".qwenpaw", ".opencode", ".codex"}

# 技能名称，用于在系统临时目录中创建子目录
_SKILL_NAME = "autotest-code"


def get_skill_temp_dir() -> Path:
    """
    获取技能专用的临时目录路径。

    返回：
        Path: 技能临时目录路径，格式为 {tempdir}/.claude-skills/autotest-code/
    """
    return Path(tempfile.gettempdir()) / ".claude-skills" / _SKILL_NAME


def get_temp_path(filename: str) -> Path:
    """
    获取临时文件的完整路径。

    参数：
        filename: 临时文件名（如 "analysis.json", "report.xml"）

    返回：
        Path: 临时文件的完整路径
    """
    temp_dir = get_skill_temp_dir()
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / filename


def is_safe_path(path: str | Path) -> bool:
    """
    验证路径是否安全（可以写入）。

    安全路径包括：
    1. 技能临时目录：{tempdir}/.claude-skills/autotest-code/
    2. 系统临时目录：tempfile.gettempdir(), /tmp, /var/tmp
    3. 允许的平台目录：~/.claude/, ~/.qwenpaw/, ~/.opencode/, ~/.codex/

    参数：
        path: 要验证的路径

    返回：
        bool: 路径是否安全
    """
    try:
        resolved = Path(os.path.expanduser(str(path))).resolve()
    except (RuntimeError, OSError):
        # Path.home() 可能失败（容器环境）或路径解析失败
        return False

    # 检查是否在技能临时目录中
    skill_temp_dir = get_skill_temp_dir()
    try:
        if resolved.is_relative_to(skill_temp_dir):
            return True
    except ValueError:
        pass

    # 检查是否在系统临时目录中
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

    # 检查是否在允许的平台目录中（向后兼容）
    try:
        home_dir = Path.home().resolve()
        if resolved.is_relative_to(home_dir):
            relative = resolved.relative_to(home_dir)
            if relative.parts:
                first_part = relative.parts[0]
                if first_part in _ALLOWED_PLATFORM_DIRS:
                    return True
    except RuntimeError:
        # Path.home() 可能失败（容器环境）
        pass

    return False


def ensure_parent_dir(path: str | Path) -> Path:
    """
    确保路径的父目录存在。

    参数：
        path: 文件路径

    返回：
        Path: 解析后的路径
    """
    resolved = Path(os.path.expanduser(str(path))).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved
