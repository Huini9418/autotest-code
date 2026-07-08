# -*- coding: utf-8 -*-
"""analyze.py main() 入口测试。

覆盖：路径不存在、--lang 指定、自动检测、--output 写文件、stdout 输出。
"""
import json
import os
import subprocess
import sys

import pytest

# 获取 scripts 目录
VARIANT = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "skills", VARIANT, "scripts"
))


def _run_analyze(target_path, lang=None, output=None):
    """运行 analyze.py 并返回 CompletedProcess。"""
    script = os.path.join(SCRIPTS_DIR, "analyze.py")
    cmd = [sys.executable, script, str(target_path)]
    if lang:
        cmd.extend(["--lang", lang])
    if output:
        cmd.extend(["--output", str(output)])
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )


class TestAnalyzeMain:
    """analyze.py CLI 入口测试。"""

    def test_target_path_not_found_exit_1(self):
        """目标路径不存在时退出码 1。"""
        result = _run_analyze("/nonexistent/path/to/file.py")
        assert result.returncode == 1
        assert "not found" in result.stderr.lower()

    def test_lang_python_explicit(self, tmp_path):
        """--lang python 正确分析。"""
        f = tmp_path / "sample.py"
        f.write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
        result = _run_analyze(str(f), lang="python")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "files" in data
        assert "summary" in data
        assert data["summary"]["total_functions"] >= 1

    def test_auto_detect_python(self, tmp_path):
        """省略 --lang 时自动检测 Python。"""
        f = tmp_path / "sample.py"
        f.write_text("def foo(x: int) -> int:\n    return x\n")
        result = _run_analyze(str(f))
        assert result.returncode == 0
        assert "Auto-detected language" in result.stderr
        data = json.loads(result.stdout)
        assert data["summary"]["total_files"] >= 1

    def test_output_to_file(self, tmp_path):
        """--output 将结果写入文件。"""
        f = tmp_path / "sample.py"
        f.write_text("def foo():\n    pass\n")
        output_file = tmp_path / "analysis.json"
        result = _run_analyze(str(f), lang="python", output=output_file)
        assert result.returncode == 0
        assert "Analysis written to" in result.stderr
        assert output_file.exists()
        data = json.loads(output_file.read_text(encoding="utf-8"))
        assert "files" in data

    def test_output_creates_parent_dirs(self, tmp_path):
        """--output 自动创建父目录。"""
        f = tmp_path / "sample.py"
        f.write_text("def foo():\n    pass\n")
        output_file = tmp_path / "deep" / "nested" / "analysis.json"
        result = _run_analyze(str(f), lang="python", output=output_file)
        assert result.returncode == 0
        assert output_file.exists()

    def test_stdout_output_when_no_output_flag(self, tmp_path):
        """无 --output 时结果输出到 stdout。"""
        f = tmp_path / "sample.py"
        f.write_text("def foo():\n    pass\n")
        result = _run_analyze(str(f), lang="python")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "files" in data

    def test_analyze_directory(self, tmp_path):
        """分析目录下多个文件。"""
        (tmp_path / "a.py").write_text("def a():\n    pass\n")
        (tmp_path / "b.py").write_text("def b():\n    pass\n")
        result = _run_analyze(str(tmp_path), lang="python")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["summary"]["total_files"] >= 2

    def test_empty_file_produces_no_functions(self, tmp_path):
        """空文件分析不报错。"""
        f = tmp_path / "empty.py"
        f.write_text("")
        result = _run_analyze(str(f), lang="python")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["summary"]["total_functions"] == 0
