---
name: autotest-code
description: "Use when users need to generate tests for project code. Supports Python/JavaScript/TypeScript/Go/Rust/Java. Triggers include 'generate tests', 'write unit tests', 'write test for this function', 'auto test', 'generate tests', 'automated testing'. Covers full loop: analyze → design → generate → execute → fix → iterate."
metadata:
  builtin_skill_version: "2.0"
---

# Automated Test Generation (Multi-language)

Automatically generate tests for your project code, run them, and iteratively fix failures. Supports multiple languages:
Python / JavaScript / TypeScript / Go / Rust / Java.

> **Path convention**: All `scripts/` paths are relative to this skill directory.
> When using `execute_shell_command`, set `cwd` to the skill directory,
> or use absolute path `python3 <skill_dir>/scripts/xxx.py`.

## When to Use / When Not to Use

### Should Use
- User asks to "generate tests", "write unit tests", "write test for this function"
- User asks for "auto test", "automated testing", "generate tests"
- User wants to add tests for a file/directory/function
- User wants to improve code coverage

### Should Not Use
- User is just asking "how to write tests" (answer directly, no full flow needed)
- User wants to test the skill scripts themselves

## Execution Flow

### Step 0: Environment Detection

#### 0a: Python Environment Discovery (Python projects only)

If target language is detected as Python, first run environment discovery to list all available Python environments on the system:

```bash
execute_shell_command(
    command="mkdir -p ~/.claude/tmp/ && python3 <skill_dir>/scripts/discover_python_envs.py <target_path> --output ~/.claude/tmp/python_envs.json",
    cwd="<skill_dir>"
)
```

Read `~/.claude/tmp/python_envs.json` and **present environment list to user**:

```
Detected the following Python environments:
1. /Users/foo/.venv/bin/python (Python 3.11.5, project_venv, has pytest 8.0.0) ← recommended
2. /usr/local/bin/python3 (Python 3.12.0, homebrew, no pytest)
3. /usr/bin/python3 (Python 3.9.6, system, no pytest)

Please select a Python environment (enter number):
```

Wait for user selection, then save the selected path to `~/.claude/tmp/selected_python.txt`.

> If `environments` is empty list, skip this step and fall back to `0b` without passing `--python`.
> `recommended` field is default recommendation and can be suggested directly to user.

#### 0b: Language and Toolchain Detection

```bash
execute_shell_command(
    command="python3 <skill_dir>/scripts/detect_lang.py <target_path> --python <selected_python> --output ~/.claude/tmp/lang_detect.json && rm -f ~/.claude/failure_history.json",
    cwd="<skill_dir>"
)
```

> If `0a` was not executed or user did not select, remove `--python <selected_python>` parameter.

Read `~/.claude/tmp/lang_detect.json`, confirm:
- **language**: target language (python/javascript/typescript/go/rust/java)
- **framework**: testing framework (pytest/jest/vitest/go test/cargo nextest/maven)
- **toolchain**: whether toolchain is available, prompt for installation if missing
  - `python_path`: selected Python interpreter path (Python only, used in later steps)
- **tree_sitter**: whether tree-sitter dependency is available (not needed for Python)
- **pytest_plugins**: pytest plugin detection for Python projects (Python only)
  - `plugins`: availability dict for each plugin, key is package name (e.g., `pytest-mock`), value includes:
    - `available`: whether installed
    - `trigger_type`: trigger type (fixture/marker/decorator)
    - `trigger`: trigger identity (e.g., `mocker`, `@pytest.mark.asyncio`)
    - `alt`: alternative
  - `asyncio_mode`: whether asyncio_mode configured (auto/strict/empty)
  - `pytest_asyncio`: whether pytest-asyncio installed (backward compatible)
  - `anyio`: whether anyio installed (backward compatible)
  - `missing`: list of required missing plugins
  - `hints`: list of installation hints
  - `hint`: installation hint string (backward compatible)

Must clear residual failure history file before start: `rm -f ~/.claude/failure_history.json`
(prevents `stop=true` false positives from last session's residual data)

**Plugin usage constraints** (Python):
- Only plugins with `plugins[<package name>].available=true` can be used in tests
- `pytest-mock` not available → use `unittest.mock.patch` / `MagicMock`
- `hypothesis` not available → use `@pytest.mark.parametrize` parameterized tests
- `pytest-benchmark` not available → use `time.perf_counter()` manual timing
- `pytest-subtests` not available → use multiple independent test functions
- `pytest-freezegun` not available → use `freezegun.freeze_time()` or `unittest.mock.patch`
- `responses` not available → use `unittest.mock.patch` to mock requests

If toolchain or tree-sitter dependencies are missing, **inform user first** what needs to be installed,
wait for user confirmation before continuing.

**Async test plugin notes** (Python):
- If `pytest_plugins.missing` includes `pytest-asyncio`,
  **inform user first** to install: `pip install pytest-asyncio`
- Or use `@pytest.mark.anyio` in Step 3 test generation (if anyio is installed)
- **Do not** use `@pytest.mark.asyncio` without pytest-asyncio installed,
  will cause all async tests to fail

Location rules:
- User gave file path → use directly
- User only gave function name → use `grep_search` to locate file in project searching `def <name>` / `function <name>`
- Coding Mode → take current open file
- User gave directory → recursively analyze all source files in directory

### Step 1: AST Analysis

```bash
execute_shell_command(
    command="python3 <skill_dir>/scripts/analyze.py <target_path> --lang <lang> --output ~/.claude/tmp/analysis.json",
    cwd="<skill_dir>"
)
```

Read `~/.claude/tmp/analysis.json`, understand:
- Function signatures (parameters, type annotations, default values)
- Number of branch nodes (if/for/while/try/except/BoolOp)
- import dependencies
- Complexity (cyclomatic complexity)
- Class and method structure

> Python uses `ast` module (zero dependency), other languages use tree-sitter.
> Adapters discovered dynamically via `lang/*_lang.py`, add new language just by adding a file.

### Step 2: Test Case Design

```bash
execute_shell_command(
    command="python3 <skill_dir>/scripts/gen_cases.py --analysis-file ~/.claude/tmp/analysis.json --lang <lang> --output ~/.claude/tmp/cases.json",
    cwd="<skill_dir>"
)
```

Read `~/.claude/tmp/cases.json`, get structured test case list, including four types:
- **equivalence_class**: normal values derived from type annotations
- **boundary_value**: boundary value table by parameter type
- **exception_path**: generated when number of branches > 0
- **decision_table**: generated when number of branches >= 3

> Test case design algorithm is language-independent (`case_design.py`), TYPE_BOUNDARIES
> injected by language.

### Step 3: Generate Test Code

Based on test case list, **you (LLM)** generate the test code. Rules:

#### General Rules
1. **Naming conventions**: follow language idiomatic naming
2. **Parameterization**: use parameterization mechanism for similar boundary values
3. **Fixture/setup**: extract repeated construction logic into fixture/setup
4. **Mock**: mock external dependencies (network, filesystem, database)
5. **Exception assertions**: use language idiomatic exception assertions
6. **Import**: prefer standard imports, use language idiomatic solutions if path doesn't work
7. **Coverage goal**: every test case list item must have a corresponding test
8. **Isolation**: not dependent on test execution order, no global side effects

#### Language Idiomatic Patterns

**Python (pytest)**
- File naming: `test_<name>.py`, function `test_<name>_<scenario>`
- Parameterization: `@pytest.mark.parametrize`
- Exception: `with pytest.raises(ExpectedError):`
- Mock: `unittest.mock.patch`
- Placement: `tests/` directory
- **Plugin usage** (check `pytest_plugins.plugins` in `~/.claude/tmp/lang_detect.json`):
  - `mocker` fixture not available → use `unittest.mock.patch` / `MagicMock`
  - `@given` not available → use `@pytest.mark.parametrize` parameterized tests
  - `benchmark` fixture not available → use `time.perf_counter()` manual timing
  - `subtests` fixture not available → use multiple independent test functions
  - `freezer` fixture not available → use `freezegun.freeze_time()` or `unittest.mock.patch`
  - `@responses.activate` not available → use `unittest.mock.patch` to mock requests
- Async tests:
  - Check `pytest_plugins` field in `~/.claude/tmp/lang_detect.json`
  - `pytest_asyncio=true` → use `@pytest.mark.asyncio`
  - `pytest_asyncio=false` but `anyio=true` → use `@pytest.mark.anyio`
  - Both missing → **inform user first to install**, don't generate async tests

**JavaScript/TypeScript (Jest)**
- File naming: `<name>.test.js` / `<name>.test.ts` (colocated)
- Structure: `describe('Module', () => { it('should ...', () => {}) })`
- Assertions: `expect(result).toBe(expected)`
- Exceptions: `expect(() => fn()).toThrow(Error)`
- Mock: `jest.mock('module')` / `vi.mock('module')`
- Async: `async/await`, `expect(promise).resolves.toBe(x)`

**Go**
- File naming: `<name>_test.go` (same directory)
- Function: `func TestName(t *testing.T)`
- Table-driven: `tests := []struct{...}{...}` + `for _, tt := range tests`
- Assertions: `if got != want { t.Errorf(...) }`
- Placement: same directory as source file

**Rust**
- File naming: `tests/<name>.rs` or inline `#[cfg(test)]`
- Function: `#[test] fn test_name()`
- Assertions: `assert_eq!(got, want)` / `assert!(condition)`
- Exceptions: `#[should_panic(expected = "...")]`
- Placement: `tests/` directory or inline `mod tests`

**Java (JUnit)**
- File naming: `<Name>Test.java`, placed in `src/test/java/`
- Method: `@Test void testName()`
- Assertions: `assertEquals(expected, actual)`
- Exceptions: `assertThrows(ExpectedException.class, () -> ...)`
- Mock: `@Mock` + `Mockito.when()`

Use `write_file` to write test code to corresponding test directory in project.

### Step 4: Execute Tests

Select execution command by language, output JUnit XML uniformly:

| Language | Command |
|----------|---------|
| Python | `<python_path> -m pytest <test_path> --junitxml=~/.claude/tmp/report.xml -v --tb=short` (use `toolchain.python_path` instead of `python3` when it exists, otherwise fall back to `python3 -m pytest ...`) |
| JS/TS | `npx jest --reporters=junit --outputFile=~/.claude/tmp/report.xml <test_path>` |
| Go | `gotestsum --junitfile=~/.claude/tmp/report.xml -- <test_path>` |
| Rust | `cargo nextest run --junit-path=~/.claude/tmp/report.xml <test_path>` |
| Java | `mvn test -Dtest=<test_class> ; for f in target/surefire-reports/*.xml; do cp "$f" ~/.claude/tmp/report.xml; break; done 2>/dev/null; true` |

```bash
execute_shell_command(
    command="<test_command> 2>&1 | tail -200; true",
    cwd="<project_dir>"
)
```

Notes:
- `--junitxml` / `--outputFile` / `--junitfile` is required for next step parsing
- `2>&1 | tail -200` prevents output from being too long
- `; true` ensures shell command doesn't non-zero exit due to test failure
- `cwd` must be project root directory to ensure import paths are correct

### Step 5: Parse Failures

```bash
execute_shell_command(
    command="python3 <skill_dir>/scripts/parse_failures.py --junitxml ~/.claude/tmp/report.xml --lang <lang> --history-file ~/.claude/failure_history.json --output ~/.claude/tmp/failures.json",
    cwd="<skill_dir>"
)
```

Read `~/.claude/tmp/failures.json`, get:
- **summary**: total, passed, failed, error, build_errors, pass rate
- **failures**: classification, severity, suggestion for each failure
- **all_cases**: all test case statuses
- **stop**: whether repeated failure signature detected (`true` means should stop iteration)
- **repeat_count**: number of times current failure signature has repeated

### Step 6: Analyze Failures

Decide how to handle based on `severity` field:

| severity | Meaning | Handling |
|----------|---------|----------|
| `test_logic` | Test code is wrong | Fix test code |
| `test_setup` | Test environment/config issue | Fix conftest or fixture |
| `missing_plugin` | pytest plugin not installed | Install plugin or use alternative |
| `target_bug` | Suspected source bug | **Do not modify source**, report to user |
| `test_env` | Runtime environment issue | Check dependency installation, path permissions |
| `build_error` | Compiled language build failed | Fix compilation errors then rebuild |

### Step 7: Auto Fix and Iterate (Maximum 2 rounds)

1. **Check `stop` field**: If `~/.claude/tmp/failures.json` has `stop=true`, meaning
   failure signature is same as last round (same test failed same way), **stop iteration immediately**,
   summarize and report to user
2. For `test_logic` / `test_setup` / `missing_plugin` failures, use `edit_file`
   to fix test code (install plugin or use alternative for `missing_plugin`)
3. For `build_error` failures, fix compilation errors (syntax/type/dependency)
4. Re-execute Step 4-5 (second round can only run last failed tests to speed up iteration)
5. Repeat until all passed, or hit **2 round limit**
6. Still have failures when hitting limit → stop, summarize and report to user

**Hard rules**:
- **Must stop iteration when `stop=true`**, don't keep fixing tests, directly report to user
- **Do not modify target code** (source files), only fix test code
- Suspected `target_bug` failure → report to user, let user decide
- Don't delete test cases just to "make tests pass"

## Output Report

After flow completes, report to user:
1. **Language detection**: detected language, framework, toolchain status
2. **Analysis summary**: which files analyzed, how many functions/classes
3. **Test generation**: how many test cases generated, what types covered
4. **Execution result**: pass rate, number of failures, number of build errors
5. **Iteration rounds**: how many rounds of fixes
6. **Remaining failures** (if any): list by severity, with suggestions
7. **Suspected bugs** (if any): mark `target_bug` failures, ask user to confirm

## Multi-language Architecture

Three-layer architecture design:
- **Layer 1 AST Analysis**: Python uses `ast` module (zero dependency), other languages use tree-sitter standalone packages
- **Layer 2 Test Case Design**: language-independent shared algorithm (`case_design.py`)
- **Layer 3 Language Adapter**: test commands, failure rules, file placement (`registry.py`)

`lang/` directory dynamically discovers adapters:
- `lang/__init__.py` — register decorator + get_analyzer dispatcher + dynamic scan of `*_lang.py`
- `lang/base.py` — BaseAnalyzer abstract base class
- `lang/case_design.py` — four test case design shared algorithms
- `lang/registry.py` — language → command/rule/file placement mapping
- `lang/python_lang.py` — Python adapter (using `ast` module, zero dependency)
- `lang/javascript_lang.py` — JavaScript adapter (tree-sitter-javascript)
- `lang/typescript_lang.py` — TypeScript adapter (tree-sitter-typescript)
- `lang/go_lang.py` — Go adapter (tree-sitter-go)
- `lang/rust_lang.py` — Rust adapter (tree-sitter-rust)
- `lang/java_lang.py` — Java adapter (tree-sitter-java)
- Add new language: create `lang/<lang>_lang.py`, implement `analyze`/`gen_cases`, register with `@register`

> Non-Python languages need to install corresponding tree-sitter package (see `scripts/requirements.txt`).
> `detect_lang.py` `tree_sitter` field will detect if dependency is available, prompt for installation if missing.
> Single adapter loading failure doesn't affect other adapters (`__init__.py` has try/except error isolation).
