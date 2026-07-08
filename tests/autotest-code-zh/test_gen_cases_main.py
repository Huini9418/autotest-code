# -*- coding: utf-8 -*-
"""gen_cases.py main() 入口测试。

覆盖：分析文件不存在、--lang 默认 python、--output 写文件、
--filter 功能、stdout 输出。
"""
import json
import os
import subprocess
import sys

import pytest

from lang import get_analyzer

# 获取 scripts 目录
VARIANT = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "skills", VARIANT, "scripts"
))


def _run_gen_cases(analysis_file, lang=None, filter_str=None, output=None):
    """运行 gen_cases.py 并返回 CompletedProcess。"""
    script = os.path.join(SCRIPTS_DIR, "gen_cases.py")
    cmd = [sys.executable, script, "--analysis-file", str(analysis_file)]
    if lang:
        cmd.extend(["--lang", lang])
    if filter_str:
        cmd.extend(["--filter", filter_str])
    if output:
        cmd.extend(["--output", str(output)])
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def analysis_file(tmp_path):
    """生成一个分析结果文件供 gen_cases.py 使用。"""
    f = tmp_path / "sample.py"
    f.write_text(
        "def divide(a: int, b: int = 1) -> float:\n"
        "    if b == 0:\n"
        "        raise ValueError()\n"
        "    return a / b\n"
    )
    analyzer = get_analyzer("python")
    analysis = analyzer.analyze(str(f))
    analysis_path = tmp_path / "analysis.json"
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False))
    return analysis_path


class TestGenCasesMain:
    """gen_cases.py CLI 入口测试。"""

    def test_analysis_file_not_found_exit_1(self, tmp_path):
        """分析文件不存在时退出码 1。"""
        result = _run_gen_cases(tmp_path / "nonexistent.json")
        assert result.returncode == 1
        assert "not found" in result.stderr.lower()

    def test_default_lang_is_python(self, analysis_file):
        """不传 --lang 时默认 python。"""
        result = _run_gen_cases(analysis_file)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "test_cases" in data
        assert "summary" in data

    def test_lang_python_explicit(self, analysis_file):
        """--lang python 正确生成。"""
        result = _run_gen_cases(analysis_file, lang="python")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data["test_cases"]) > 0

    def test_output_to_file(self, analysis_file, tmp_path):
        """--output 将结果写入文件。"""
        output_file = tmp_path / "cases.json"
        result = _run_gen_cases(analysis_file, output=output_file)
        assert result.returncode == 0
        assert "Cases written to" in result.stderr
        assert output_file.exists()
        data = json.loads(output_file.read_text(encoding="utf-8"))
        assert "test_cases" in data

    def test_output_creates_parent_dirs(self, analysis_file, tmp_path):
        """--output 自动创建父目录。"""
        output_file = tmp_path / "deep" / "nested" / "cases.json"
        result = _run_gen_cases(analysis_file, output=output_file)
        assert result.returncode == 0
        assert output_file.exists()

    def test_stdout_output_when_no_output_flag(self, analysis_file):
        """无 --output 时结果输出到 stdout。"""
        result = _run_gen_cases(analysis_file)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "test_cases" in data

    def test_filter_matches_function(self, analysis_file):
        """--filter 匹配函数名。"""
        result = _run_gen_cases(analysis_file, filter_str="divide")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        for tc in data["test_cases"]:
            assert "divide" in tc["target"].lower()

    def test_filter_no_match_returns_empty(self, analysis_file):
        """--filter 不匹配时返回空用例列表。"""
        result = _run_gen_cases(analysis_file, filter_str="nonexistent_func")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data["test_cases"]) == 0
        assert data["summary"]["total_cases"] == 0

    def test_filter_recalculates_summary(self, analysis_file):
        """--filter 后 summary 重新计算。"""
        result = _run_gen_cases(analysis_file, filter_str="divide")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        total = data["summary"]["total_cases"]
        by_type_sum = sum(data["summary"]["by_type"].values())
        assert total == by_type_sum
        assert total == len(data["test_cases"])
