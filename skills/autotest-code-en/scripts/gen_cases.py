#!/usr/bin/env python3
"""用例设计入口。

动态发现 lang/*_lang.py 适配器，调用共享的 case_design.py 算法。
TYPE_BOUNDARIES / TYPE_NORMALS 作为每语言独立数据注入。
"""

import argparse
import json
import os
import sys
from pathlib import Path

# 确保 lang 包可被导入（无论 cwd 在哪）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lang import get_analyzer, list_languages  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="基于分析结果生成测试用例清单（多语言支持）"
    )
    parser.add_argument(
        "--analysis-file",
        required=True,
        help="analyze.py 的 JSON 输出文件",
    )
    parser.add_argument(
        "--lang",
        help=(
            "目标语言（省略时默认 python）。"
            f"支持: {', '.join(list_languages())}"
        ),
    )
    parser.add_argument(
        "--filter",
        help="只生成匹配函数名的用例（支持子串匹配）",
    )
    parser.add_argument(
        "--output",
        help="输出文件路径（可选，默认 stdout）",
    )
    args = parser.parse_args()

    analysis_path = Path(args.analysis_file)
    if not analysis_path.exists():
        print(
            f"Error: analysis file not found: {analysis_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    analysis = json.loads(
        analysis_path.read_text(encoding="utf-8")
    )

    # 确定语言：--lang 优先，否则默认 python
    lang = args.lang or "python"
    analyzer = get_analyzer(lang)
    result = analyzer.gen_cases(analysis)

    if args.filter:
        cases = result.get("test_cases", [])
        filter_lower = args.filter.lower()
        filtered = [
            tc
            for tc in cases
            if filter_lower in tc.get("target", "").lower()
        ]
        result["test_cases"] = filtered
        by_type: dict[str, int] = {}
        for tc in filtered:
            t = tc.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        result["summary"] = {
            "total_cases": len(filtered),
            "by_type": by_type,
        }

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(os.path.expanduser(args.output))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Cases written to {out_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
