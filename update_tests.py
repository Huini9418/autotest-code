#!/usr/bin/env python3
"""Update all test files to use the new path structure."""

import os
import re

TEST_DIR = os.path.dirname(os.path.abspath(__file__)) / "tests"


def update_file(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Pattern to match the old VARIANT and SCRIPTS_DIR setup
    old_pattern = r'^(# 获取 scripts 目录\n)?VARIANT = os.path.basename\(os.path.dirname\(os.path.abspath\(__file__\)\)\)\nSCRIPTS_DIR = os.path.normpath\(os.path.join\(\n\s+os.path.dirname\(os.path.abspath\(__file__\)\),\n\s+"\.\.", "\.\.", "skills", VARIANT,\n\s+"scripts"\n\)\)'

    new_content = '''# 获取 scripts 目录
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.normpath(os.path.join(
    TEST_DIR,
    "..", "skills", "autotest-code-zh", "scripts"
))'''

    updated = re.sub(old_pattern, new_content, content, flags=re.MULTILINE)

    if updated != content:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(updated)
        print(f"Updated: {file_path}")
    else:
        # Try a simpler pattern
        content2 = content
        content2 = re.sub(
            r'^VARIANT = os.path.basename\(os.path.dirname\(os.path.abspath\(__file__\)\)\)\n',
            'TEST_DIR = os.path.dirname(os.path.abspath(__file__))\n',
            content2,
            flags=re.MULTILINE
        )
        content2 = re.sub(
            r'os.path.dirname\(os.path.abspath\(__file__\)\),\s+"\.\.",\s+"\.\.",\s+"skills",\s+VARIANT',
            'TEST_DIR, "..", "skills", "autotest-code-zh"',
            content2
        )
        if content2 != content:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content2)
            print(f"Updated (method 2): {file_path}")


def main():
    tests_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests")
    for filename in os.listdir(tests_dir):
        if filename.startswith("test_") and filename.endswith(".py"):
            file_path = os.path.join(tests_dir, filename)
            update_file(file_path)


if __name__ == "__main__":
    main()
