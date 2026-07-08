#!/usr/bin/env python3
"""AST 分析入口。

动态发现 lang/*_lang.py 适配器，支持 --lang 指定和自动检测。
Python 用 ast 模块，其他语言用 tree-sitter。
"""

import argparse
import json
import os
import sys
from pathlib import Path

# 确保 lang 包可被导入（无论 cwd 在哪）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lang import get_analyzer, list_languages  # noqa: E402
# lang/__init__.py 在 import 时自动 _discover_languages()，无需手动 import

# 延迟导入 detect_lang 避免在仅用 --lang 时产生不必要的依赖
if os.path.exists(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "detect_lang.py")
):
    from detect_lang import detect_language  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="分析源码文件的 AST 结构（多语言支持）"
    )
    parser.add_argument(
        "target_path", help="要分析的文件或目录路径"
    )
    parser.add_argument(
        "--lang",
        help=(
            "目标语言（省略时自动检测）。"
            f"支持: {', '.join(list_languages())}"
        ),
    )
    parser.add_argument(
        "--output",
        help="输出文件路径（可选，默认 stdout）",
    )
    args = parser.parse_args()

    if not os.path.exists(args.target_path):
        print(
            f"Error: target path not found: {args.target_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    # 确定语言：--lang 优先，否则自动检测
    lang = args.lang
    if not lang:
        lang = detect_language(args.target_path)
        print(f"Auto-detected language: {lang}", file=sys.stderr)

    analyzer = get_analyzer(lang)
    result = analyzer.analyze(args.target_path)

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(os.path.expanduser(args.output))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Analysis written to {out_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
