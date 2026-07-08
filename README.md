# auto_test — Automated Test Generation Skill

[中文](#中文) | [English](#english)

---

## 中文

### 简介

`auto_test` 是一个 **Claude Code Skill**，能为你的项目代码自动生成测试、执行并迭代修复，覆盖从分析到最终通过的完整闭环。

支持语言：**Python · JavaScript · TypeScript · Go · Rust · Java**

### 安装

#### 方式一：Plugin 命令安装（推荐）

```
/plugin marketplace add Huini9418/autotest-code
/plugin install autotest-code@autotest-code    # 中文版
/plugin install autotest-code-en@autotest-code    # 英文版
```

#### 方式二：手动安装

```bash
git clone https://github.com/Huini9418/autotest-code.git
# 中文版
cp -R autotest-code/skills/autotest-code-zh/ ~/.claude/skills/autotest-code/
# 英文版
cp -R autotest-code/skills/autotest-code-en/ ~/.claude/skills/autotest-code-en/
```

> 具体路径因平台而异，请参考你使用的 AI 平台文档。

### 依赖

```bash
pip install -r ~/.claude/skills/autotest-code/scripts/requirements.txt
```

还需要确保以下命令可用：

| 语言 | 工具链 |
|------|--------|
| Python | `python3`, `pytest` |
| JavaScript / TypeScript | `node`, `jest` 或 `vitest` |
| Go | `go test` |
| Rust | `cargo nextest` 或 `cargo test` |
| Java | `mvn test` 或 `gradle test` |

> JavaScript/TypeScript/Go/Rust/Java 的 AST 分析依赖 tree-sitter，安装时会自动处理。

### 使用方法

在 Claude Code 对话中，用以下任意表达触发：

```
生成测试
写单元测试
为这个函数写 test
自动化测试
提高代码覆盖率
```

Skill 会自动：
1. 检测目标语言和工具链
2. 用 AST 分析代码结构（函数签名、分支、复杂度）
3. 用等价类 / 边界值 / 异常路径 / 决策表设计用例
4. 生成测试代码并写入项目
5. 执行测试，失败则自动修复并重试

### 目录结构

```
autotest-code/
  .claude-plugin/
    plugin.json            # 商城分发元数据
  skills/
    autotest-code-zh/          # 中文版
      SKILL.md             # Skill 定义（Claude Code 读取）
      scripts/
        analyze.py         # AST 分析入口
        detect_lang.py     # 语言 & 工具链检测
        gen_cases.py       # 用例设计入口
        parse_failures.py  # 测试失败解析
        discover_python_envs.py  # Python 环境发现
        lang/              # 各语言适配器
          python_lang.py
          javascript_lang.py
          typescript_lang.py
          go_lang.py
          rust_lang.py
          java_lang.py
          case_design.py   # 用例设计算法（语言无关）
          registry.py      # 测试命令 & 文件放置规则
    autotest-code-en/          # 英文版（结构同上）
  tests/              # 单元测试（开发用，不随 skill 分发）
    autotest-code-zh/
    autotest-code-en/
```

### 开发 & 贡献

```bash
# 运行测试
python3 -m pytest tests/autotest-code-zh/ -v

# zh/en 必须保持一致，每次改 zh 后同步到 en
cp skills/autotest-code-zh/scripts/<file> skills/autotest-code-en/scripts/<file>
cp tests/autotest-code-zh/<file>          tests/autotest-code-en/<file>

# 一致性由此文件自动校验
python3 -m pytest tests/autotest-code-zh/test_consistency.py -v
```

---

## English

### Overview

`auto_test` is a **Claude Code Skill** that automatically generates tests for your project code, runs them, and iteratively fixes failures — covering the full loop from analysis to passing tests.

Supported languages: **Python · JavaScript · TypeScript · Go · Rust · Java**

### Installation

#### Method 1: Plugin command (recommended)

```
/plugin marketplace add Huini9418/autotest-code
/plugin install auto-test-zh@auto-test    # Chinese
/plugin install auto-test-en@auto-test    # English
```

#### Method 2: Manual install

```bash
git clone https://github.com/Huini9418/autotest-code.git
# English variant
cp -R autotest-code/skills/auto-test-en/ ~/.claude/skills/auto-test/
# Chinese variant
cp -R autotest-code/skills/auto-test-zh/ ~/.claude/skills/auto-test/
```

> The exact path depends on your AI platform. Check its documentation.

### Dependencies

```bash
pip install -r ~/.claude/skills/autotest-code/scripts/requirements.txt
```

Also ensure the relevant toolchain is available:

| Language | Toolchain |
|----------|-----------|
| Python | `python3`, `pytest` |
| JavaScript / TypeScript | `node`, `jest` or `vitest` |
| Go | `go test` |
| Rust | `cargo nextest` or `cargo test` |
| Java | `mvn test` or `gradle test` |

> AST analysis for JS/TS/Go/Rust/Java relies on tree-sitter, which is handled automatically by the requirements file.

### Usage

Trigger the skill in a Claude Code conversation with any of:

```
generate tests
write unit tests
write test for this function
auto test
improve code coverage
```

The skill will automatically:
1. Detect the target language and toolchain
2. Analyze code structure via AST (signatures, branches, complexity)
3. Design test cases using equivalence class / boundary value / exception path / decision table techniques
4. Write the generated tests into your project
5. Run the tests and auto-fix any failures, retrying until they pass

### Repository Layout

```
autotest-code/
  .claude-plugin/
    plugin.json            # Marketplace metadata
  skills/
    autotest-code-zh/          # Chinese variant
      SKILL.md             # Skill definition (read by Claude Code)
      scripts/
        analyze.py         # AST analysis entry point
        detect_lang.py     # Language & toolchain detection
        gen_cases.py       # Test case design entry point
        parse_failures.py  # Test failure parser
        discover_python_envs.py  # Python environment discovery
        lang/              # Per-language adapters
          python_lang.py
          javascript_lang.py
          typescript_lang.py
          go_lang.py
          rust_lang.py
          java_lang.py
          case_design.py   # Language-agnostic case design algorithm
          registry.py      # Test commands & file placement rules
    autotest-code-en/          # English variant (same structure)
  tests/              # Unit tests (for development, not shipped with skill)
    autotest-code-zh/
    autotest-code-en/
```

### Development & Contributing

```bash
# Run tests
python3 -m pytest tests/autotest-code-zh/ -v

# zh and en must stay in sync — after editing zh, copy to en:
cp skills/autotest-code-zh/scripts/<file> skills/autotest-code-en/scripts/<file>
cp tests/autotest-code-zh/<file>          tests/autotest-code-en/<file>

# Consistency is enforced automatically by:
python3 -m pytest tests/autotest-code-zh/test_consistency.py -v
```

### License

MIT
