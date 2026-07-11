---
name: autotest-code
description: "当用户需要为项目代码生成测试时使用。支持 Python/JavaScript/TypeScript/Go/Rust/Java 多语言。触发表达包括「生成测试」「写单元测试」「为这个函数写 test」「auto test」「generate tests」「自动化测试」。覆盖分析→设计→生成→执行→修复→迭代的完整闭环。"
metadata:
  builtin_skill_version: "2.0"
---

# 自动化测试生成（多语言）

为用户的项目代码自动生成测试，执行并迭代修复。支持多语言：
Python / JavaScript / TypeScript / Go / Rust / Java。

> **路径约定：** 所有 `scripts/` 路径均相对于此技能目录。
> 用 `execute_shell_command` 运行时，设 `cwd` 为技能目录，
> 或用绝对路径 `python3 <skill_dir>/scripts/xxx.py`。
>
> **临时文件位置：** 临时文件和历史文件使用以下位置：
> - 推荐：`{tempdir}/.claude-skills/autotest-code/`（跨平台系统临时目录）
> - 向后兼容：`~/.claude/`、`~/.qwenpaw/`、`~/.opencode/`、`~/.codex/`
>
> **重要说明：**
> - 文档中 `{skill_temp_dir}/` 是一个**占位符标记**，不是实际变量
> - 实际使用时，需要用代码动态获取：
>   ```python
>   import tempfile
>   from pathlib import Path
>   skill_temp_dir = Path(tempfile.gettempdir()) / ".claude-skills" / "autotest-code"
>   ```
> - 或者使用提供的工具：`from utils.temp_dir import get_temp_path`
>
> 注：`{tempdir}` = `tempfile.gettempdir()`（Unix 上是 `/tmp`，Windows 上是 `%TEMP%`）

## 什么时候用 / 什么时候不用

### 应该使用
- 用户要求「生成测试」「写单元测试」「为这个函数写 test」
- 用户要求「自动化测试」「auto test」「generate tests」
- 用户想为某个文件/目录/函数补充测试
- 用户想提高代码覆盖率

### 不应使用
- 用户只是问「怎么写测试」（直接回答即可，无需走全流程）
- 用户要求测试的是当前正在编辑的 skill 脚本本身

## 执行流程

### Step 0: 环境检测

#### 0a: Python 环境发现（仅 Python 项目）

如果目标语言检测为 Python，先运行环境发现，列出系统上所有可用的 Python 环境：

```bash
execute_shell_command(
    command="mkdir -p {skill_temp_dir}/ && python3 <skill_dir>/scripts/discover_python_envs.py <target_path> --output {skill_temp_dir}/python_envs.json",
    cwd="<skill_dir>"
)
```

读取 `{skill_temp_dir}/python_envs.json`，将环境列表**展示给用户**：

```
检测到以下 Python 环境：
1. /Users/foo/.venv/bin/python (Python 3.11.5, project_venv, has pytest 8.0.0) ← 推荐
2. /usr/local/bin/python3 (Python 3.12.0, homebrew, no pytest)
3. /usr/bin/python3 (Python 3.9.6, system, no pytest)

请选择要使用的 Python 环境（输入序号）：
```

等待用户选择后，将选中的路径存入 `{skill_temp_dir}/selected_python.txt`。

> 如果 `environments` 为空列表，跳过此步，回退到 `0b` 不传 `--python`。
> `recommended` 字段是默认推荐项，可直接建议给用户。

#### 0b: 语言和工具链检测

```bash
execute_shell_command(
    command="python3 <skill_dir>/scripts/detect_lang.py <target_path> --python <selected_python> --output {skill_temp_dir}/lang_detect.json && rm -f {skill_temp_dir}/failure_history.json",
    cwd="<skill_dir>"
)
```

> 如果 `0a` 未执行或用户未选择，去掉 `--python <selected_python>` 参数即可。

读取 `{skill_temp_dir}/lang_detect.json`，确认：
- **language**：目标语言（python/javascript/typescript/go/rust/java）
- **framework**：测试框架（pytest/jest/vitest/go test/cargo nextest/maven）
- **toolchain**：工具链是否可用，缺失时提示用户安装
  - `python_path`：选中的 Python 解释器路径（仅 Python，后续步骤使用）
- **tree_sitter**：tree-sitter 依赖是否可用（Python 不需要）
- **pytest_plugins**：Python 项目的 pytest 插件检测（仅 Python）
  - `plugins`：各插件的可用性字典，key 为包名（如 `pytest-mock`），value 含：
    - `available`：是否已安装
    - `trigger_type`：触发类型（fixture/marker/decorator）
    - `trigger`：触发标识（如 `mocker`、`@pytest.mark.asyncio`）
    - `alt`：替代方案
  - `asyncio_mode`：是否配置了 asyncio_mode（auto/strict/空）
  - `pytest_asyncio`：pytest-asyncio 是否已安装（向后兼容）
  - `anyio`：anyio 是否已安装（向后兼容）
  - `missing`：缺失的必需插件列表
  - `hints`：安装提示列表
  - `hint`：安装提示字符串（向后兼容）

开始前必须清空残留的失败历史文件：`rm -f {skill_temp_dir}/failure_history.json`
（防止上次会话的残留数据导致 `stop=true` 误判）

**插件使用约束**（Python）：
- 只有 `plugins[<包名>].available=true` 的插件才能在测试中使用
- `pytest-mock` 不可用 → 用 `unittest.mock.patch` / `MagicMock`
- `hypothesis` 不可用 → 用 `@pytest.mark.parametrize` 参数化测试
- `pytest-benchmark` 不可用 → 用 `time.perf_counter()` 手动计时
- `pytest-subtests` 不可用 → 用多个独立测试函数
- `pytest-freezegun` 不可用 → 用 `freezegun.freeze_time()` 或 `unittest.mock.patch`
- `responses` 不可用 → 用 `unittest.mock.patch` 对 requests 打补丁

如果工具链或 tree-sitter 依赖缺失，**先告知用户**需要安装什么，
等待用户确认后再继续。

**异步测试插件注意事项**（Python）：
- 如果 `pytest_plugins.missing` 包含 `pytest-asyncio`，
  **先告知用户**安装：`pip install pytest-asyncio`
- 或者在 Step 3 生成测试时使用 `@pytest.mark.anyio`（如果 anyio 已安装）
- **不要**在未安装 pytest-asyncio 的情况下使用 `@pytest.mark.asyncio`，
  会导致所有异步测试失败

定位规则：
- 用户给了文件路径 → 直接用
- 用户只给了函数名 → 用 `grep_search` 在项目里搜索 `def <name>` / `function <name>` 定位文件
- Coding Mode 下 → 取当前打开的文件
- 用户给了目录 → 递归分析该目录下所有源文件

### Step 1: AST 分析

```bash
execute_shell_command(
    command="python3 <skill_dir>/scripts/analyze.py <target_path> --lang <lang> --output {skill_temp_dir}/analysis.json",
    cwd="<skill_dir>"
)
```

读取 `{skill_temp_dir}/analysis.json`，了解：
- 函数签名（参数、类型注解、默认值）
- 分支节点数量（if/for/while/try/except/BoolOp）
- import 依赖
- 复杂度（圈复杂度）
- 类和方法结构

> Python 用 `ast` 模块（零依赖），其他语言用 tree-sitter。
> 适配器通过 `lang/*_lang.py` 动态发现，新增语言只需加文件。

### Step 2: 用例设计

```bash
execute_shell_command(
    command="python3 <skill_dir>/scripts/gen_cases.py --analysis-file {skill_temp_dir}/analysis.json --lang <lang> --output {skill_temp_dir}/cases.json",
    cwd="<skill_dir>"
)
```

读取 `{skill_temp_dir}/cases.json`，获取结构化用例清单，包含六种类型：
- **equivalence_class**（等价类划分）：类型注解推导正常值
- **boundary_value**（边界值分析）：按参数类型的边界值表
- **exception_path**（异常路径）：分支数 > 0 时生成
- **decision_table**（决策表）：分支数 >= 3 时生成

> 用例设计算法语言无关（`case_design.py`），TYPE_BOUNDARIES
> 按语言注入。

### Step 3: 生成测试代码

基于用例清单，**你（LLM）** 来生成测试代码。规则：

#### 通用规则
1. **命名约定**：按语言惯用命名
2. **参数化**：同类边界值用参数化机制
3. **fixture/setup**：重复的构造逻辑抽成 fixture/setup
4. **mock**：外部依赖（网络、文件系统、数据库）用 mock
5. **异常断言**：用语言惯用的异常断言
6. **import**：优先标准 import，路径不通时用语言惯用方案
7. **覆盖目标**：每个用例清单条目都要有对应测试
8. **隔离性**：不依赖测试执行顺序，不写全局副作用

#### 各语言惯用模式

**Python (pytest)**
- 文件命名：`test_<name>.py`，函数 `test_<name>_<scenario>`
- 参数化：`@pytest.mark.parametrize`
- 异常：`with pytest.raises(ExpectedError):`
- mock：`unittest.mock.patch`
- 放置：`tests/` 目录
- **插件使用**（检查 `{skill_temp_dir}/lang_detect.json` 的 `pytest_plugins.plugins`）：
  - `mocker` fixture 不可用 → 用 `unittest.mock.patch` / `MagicMock`
  - `@given` 不可用 → 用 `@pytest.mark.parametrize` 参数化测试
  - `benchmark` fixture 不可用 → 用 `time.perf_counter()` 手动计时
  - `subtests` fixture 不可用 → 用多个独立测试函数
  - `freezer` fixture 不可用 → 用 `freezegun.freeze_time()` 或 `unittest.mock.patch`
  - `@responses.activate` 不可用 → 用 `unittest.mock.patch` 对 requests 打补丁
- 异步测试：
  - 检查 `{skill_temp_dir}/lang_detect.json` 的 `pytest_plugins` 字段
  - `pytest_asyncio=true` → 用 `@pytest.mark.asyncio`
  - `pytest_asyncio=false` 但 `anyio=true` → 用 `@pytest.mark.anyio`
  - 两者都缺失 → **先告知用户安装**，不要生成异步测试

**JavaScript/TypeScript (Jest)**
- 文件命名：`<name>.test.js` / `<name>.test.ts`（colocated）
- 结构：`describe('Module', () => { it('should ...', () => {}) })`
- 断言：`expect(result).toBe(expected)`
- 异常：`expect(() => fn()).toThrow(Error)`
- mock：`jest.mock('module')` / `vi.mock('module')`
- 异步：`async/await`，`expect(promise).resolves.toBe(x)`

**Go**
- 文件命名：`<name>_test.go`（同目录）
- 函数：`func TestName(t *testing.T)`
- table-driven：`tests := []struct{...}{...}` + `for _, tt := range tests`
- 断言：`if got != want { t.Errorf(...) }`
- 放置：与源文件同目录

**Rust**
- 文件命名：`tests/<name>.rs` 或 `#[cfg(test)]` 内联
- 函数：`#[test] fn test_name()`
- 断言：`assert_eq!(got, want)` / `assert!(condition)`
- 异常：`#[should_panic(expected = "...")]`
- 放置：`tests/` 目录或 `mod tests` 内联

**Java (JUnit)**
- 文件命名：`<Name>Test.java`，放置 `src/test/java/`
- 方法：`@Test void testName()`
- 断言：`assertEquals(expected, actual)`
- 异常：`assertThrows(ExpectedException.class, () -> ...)`
- mock：`@Mock` + `Mockito.when()`
- 继承基类：被测类继承父类（如 Spring 中继承抽象基类）时，用 `spy(new XxxService(mockDeps))` 构造真实对象，再 `doReturn(x).when(spy).baseMethod(...)` 打桩父类 public 方法；void 方法用 `doNothing().when(spy).method(...)`。父类方法须非 final。
- 严格模式：`@ExtendWith(MockitoExtension.class)` 默认严格，`@BeforeEach` 中未被某用例使用的 stub 会抛 `UnnecessaryStubbingException`。setUp 放通用 stub 时加 `@MockitoSettings(strictness = Strictness.LENIENT)`，或改用 `lenient().when(...)`。
- 常见陷阱：fastjson2 / fastjson 的 `JSONObject.put(k, v)` 返回**旧值**（`Map` 语义）而非 this，**不能** `new JSONObject().put(k, v)` 链式构造嵌套对象；需分行 `put` 或用 `fluentPut`。否则会把 `null` 存入，下游 `getJSONObject` 返回 null 触发 NPE。

用 `write_file` 把测试代码写入项目对应的测试目录。

### Step 4: 执行测试

按语言选择执行命令，统一输出 JUnit XML：

| 语言 | 命令 |
|------|------|
| Python | `<python_path> -m pytest <test_path> --junitxml={skill_temp_dir}/report.xml -v --tb=short`（当 `toolchain.python_path` 存在时用其替代 `python3`，否则回退到 `python3 -m pytest ...`） |
| JS/TS | `npx jest --reporters=junit --outputFile={skill_temp_dir}/report.xml <test_path>` |
| Go | `gotestsum --junitfile={skill_temp_dir}/report.xml -- <test_path>` |
| Rust | `cargo nextest run --junit-path={skill_temp_dir}/report.xml <test_path>` |
| Java | `mvn test -Dtest=<test_class> ; cp target/surefire-reports/TEST-*<test_class>.xml {skill_temp_dir}/report.xml 2>/dev/null; true` |

```bash
execute_shell_command(
    command="<test_command> 2>&1 | tail -200; true",
    cwd="<project_dir>"
)
```

注意：
- `--junitxml` / `--outputFile` / `--junitfile` 是必需的，供下一步解析
- `2>&1 | tail -200` 防止输出过长
- `; true` 确保shell命令不因测试失败而非零退出
- `cwd` 必须是项目根目录，保证 import 路径正确

### Step 5: 解析失败

```bash
execute_shell_command(
    command="python3 <skill_dir>/scripts/parse_failures.py --junitxml {skill_temp_dir}/report.xml --lang <lang> --history-file {skill_temp_dir}/failure_history.json --output {skill_temp_dir}/failures.json",
    cwd="<skill_dir>"
)
```

读取 `{skill_temp_dir}/failures.json`，获取：
- **summary**：总数、通过数、失败数、错误数、build_errors、通过率
- **failures**：每个失败的分类、severity、建议
- **all_cases**：全部用例状态
- **stop**：是否检测到重复失败签名（`true` 表示应停止迭代）
- **repeat_count**：当前失败签名重复出现的次数

### Step 6: 分析失败

根据 `severity` 字段决定处理方式：

| severity | 含义 | 处理方式 |
|----------|------|----------|
| `test_logic` | 测试代码写错了 | 修测试代码 |
| `test_setup` | 测试环境/配置问题 | 修 conftest 或 fixture |
| `missing_plugin` | pytest 插件未安装 | 安装插件或使用替代方案 |
| `target_bug` | 疑似源码 bug | **不修改源码**，报告给用户 |
| `test_env` | 运行环境问题 | 检查依赖安装、路径权限 |
| `build_error` | 编译型语言构建失败 | 修复编译错误后重新构建 |

### Step 7: 自动修复与迭代（最多 2 轮）

1. **检查 `stop` 字段**：如果 `{skill_temp_dir}/failures.json` 中 `stop=true`，说明
   失败签名与上一轮相同（同样的测试以同样的方式失败），**立即停止迭代**，
   汇总报告给用户
2. 对 `test_logic` / `test_setup` / `missing_plugin` 类失败，用 `edit_file`
   修测试代码（`missing_plugin` 时安装插件或改用替代方案）
3. 对 `build_error` 类失败，修复编译错误（语法/类型/依赖）
4. 重新执行 Step 4-5（第二轮可只跑上次失败的测试，加速迭代）
5. 重复直到全部通过，或达到 **2 轮上限**
6. 达到上限仍有失败 → 停下，汇总报告给用户

**硬规则：**
- **`stop=true` 时必须停止迭代**，不要再修测试，直接报告给用户
- **不修改目标代码**（源码文件），只修测试代码
- 疑似 `target_bug` 的失败 → 报告用户，让用户决定
- 不要为了「让测试通过」而删除测试用例

## 输出报告

流程结束后，向用户报告：
1. **语言检测**：检测到的语言、框架、工具链状态
2. **分析摘要**：分析了哪些文件、多少函数/类
3. **生成测试**：生成了多少测试用例、覆盖哪些类型
4. **执行结果**：通过率、失败数、编译错误数
5. **迭代轮次**：修了几轮
6. **剩余失败**（如有）：按 severity 分类列出，附建议
7. **疑似 bug**（如有）：标明 `target_bug` 类失败，请用户确认

## 多语言架构

三层架构设计：
- **Layer 1 AST 分析层**：Python 用 `ast` 模块（零依赖），其他语言用 tree-sitter 独立包
- **Layer 2 用例设计层**：语言无关的共享算法（`case_design.py`）
- **Layer 3 语言适配层**：测试命令、失败规则、文件放置（`registry.py`）

`lang/` 目录动态发现适配器：
- `lang/__init__.py` — register 装饰器 + get_analyzer 分发 + 动态扫描 `*_lang.py`
- `lang/base.py` — BaseAnalyzer 抽象基类
- `lang/case_design.py` — 四种用例设计共享算法
- `lang/registry.py` — 语言→命令/规则/文件放置映射
- `lang/python_lang.py` — Python 适配器（`ast` 模块，零依赖）
- `lang/javascript_lang.py` — JavaScript 适配器（tree-sitter-javascript）
- `lang/typescript_lang.py` — TypeScript 适配器（tree-sitter-typescript）
- `lang/go_lang.py` — Go 适配器（tree-sitter-go）
- `lang/rust_lang.py` — Rust 适配器（tree-sitter-rust）
- `lang/java_lang.py` — Java 适配器（tree-sitter-java）
- 添加新语言：创建 `lang/<lang>_lang.py`，实现 `analyze`/`gen_cases`，用 `@register` 注册

> 非 Python 语言需要安装对应 tree-sitter 包（见 `scripts/requirements.txt`）。
> `detect_lang.py` 的 `tree_sitter` 字段会检测依赖是否可用，缺失时提示安装。
> 单个适配器加载失败不影响其他适配器（`__init__.py` 有 try/except 错误隔离）。
