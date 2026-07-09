# CLAUDE.md

This is the standalone development repo for the **auto_test** QwenPaw skill.

## Project Layout

```
autotest-code/
  .claude-plugin/
    plugin.json       # 商城分发元数据
  skills/
    autotest-code-zh/     # 中文版（开发主体，与项目名一致）
      SKILL.md
      scripts/        # 分析/用例生成/失败解析等脚本
    autotest-code-en/     # 英文版（与 zh 保持完全一致）
      SKILL.md
      scripts/
  tests/              # 单元测试（开发用，不随 skill 分发）
  pyproject.toml      # pytest 配置
```

## Running Tests

```bash
# 运行所有测试
python3 -m pytest tests/ -v

# 单个文件
python3 -m pytest tests/test_python_adapter.py -v

# 按 marker
python3 -m pytest tests/ -m "not slow"
```

## Key Architecture

- **Layer 1 (AST 分析)**: Python 用 `ast` 模块，其他语言用 tree-sitter 独立包
- **Layer 2 (用例设计)**: `lang/case_design.py` 共享算法（等价类/边界值/异常/决策表）
- **Layer 3 (语言注册)**: `lang/registry.py` 存测试命令/失败规则/文件放置

## Sync Rule

`skills/autotest-code-zh/scripts/` 和 `skills/autotest-code-en/scripts/` **必须完全相同**（文件内容一致）。每次改 zh 后同步到 en：

```bash
cp skills/autotest-code-zh/scripts/<file> skills/autotest-code-en/scripts/<file>
```

一致性由 `tests/test_consistency.py` 自动校验。

## Supported Languages

Python, JavaScript, TypeScript, Go, Rust, Java（6 语言，tree-sitter 适配器各自独立）

## Dependencies

```bash
pip install -r skills/autotest-code-zh/scripts/requirements.txt
pip install pytest pytest-asyncio
```

## Connecting Back to QwenPaw

Built-in skill 路径（QwenPaw 主仓库）：
`src/qwenpaw/agents/skills/auto_test-zh/` 和 `auto_test-en/`

将本项目的更新同步回 QwenPaw：
```bash
cp -R skills/autotest-code-zh/ /path/to/QwenPaw/src/qwenpaw/agents/skills/auto_test-zh/
cp -R skills/autotest-code-en/ /path/to/QwenPaw/src/qwenpaw/agents/skills/auto_test-en/
```
