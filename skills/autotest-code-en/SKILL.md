---
name: auto_test
description: "Use when the user needs to generate tests for project code. Supports Python/JavaScript/TypeScript/Go/Rust/Java. Trigger expressions include 'generate tests', 'write unit tests', 'write test for this function', 'auto test', 'generate tests', 'automated testing'. Covers the full closed-loop: analyze → design → generate → execute → fix → iterate."
metadata:
  builtin_skill_version: "2.0"
  zhpaw:
    emoji: "🧪"
    requires:
      bins: [python3, pytest]
---

# Automated Test Generation (Multi-language)

Automatically generate tests for the user's project code, execute them,
and iteratively fix failures. Supports multiple languages:
Python / JavaScript / TypeScript / Go / Rust / Java.

> **Path convention:** All `scripts/` paths are relative to this skill
> directory. When using `execute_shell_command`, set `cwd` to the skill
> directory, or use absolute paths
> `python3 <skill_dir>/scripts/xxx.py`.

## When to Use / When NOT to Use

### Should Use
- User asks to "generate tests", "write unit tests", "write test for this function"
- User asks for "auto test", "automated testing", "generate tests"
- User wants to add tests for a file/directory/function
- User wants to improve code coverage

### Should NOT Use
- User is just asking "how to write tests" (answer directly, no full flow needed)
- User wants to test the skill scripts themselves

## Execution Flow

### Step 0: Environment Detection

#### 0a: Python Environment Discovery (Python projects only)

If the target language is detected as Python, first run environment discovery
to list all available Python environments on the system:

```bash
execute_shell_command(
    command="mkdir -p ~/.qwenpaw/tmp/ && python3 <skill_dir>/scripts/discover_python_envs.py <target_path> --output ~/.qwenpaw/tmp/python_envs.json",
    cwd="<skill_dir>"
)
```

Read `~/.qwenpaw/tmp/python_envs.json` and **present the environment list
to the user**:

```
Detected the following Python environments:
1. /Users/foo/.venv/bin/python (Python 3.11.5, project_venv, has pytest 8.0.0) ← recommended
2. /usr/local/bin/python3 (Python 3.12.0, homebrew, no pytest)
3. /usr/bin/python3 (Python 3.9.6, system, no pytest)

Please select a Python environment (enter number):
```

Wait for the user to choose, then save the selected path to
`~/.qwenpaw/tmp/selected_python.txt`.

> If `environments` is an empty list, skip this step and fall back to `0b`
> without passing `--python`.
> The `recommended` field is the default recommendation and can be suggested
> to the user directly.

#### 0b: Language and Toolchain Detection

```bash
execute_shell_command(
    command="python3 <skill_dir>/scripts/detect_lang.py <target_path> --python <selected_python> --output ~/.qwenpaw/tmp/lang_detect.json && rm -f ~/.qwenpaw/failure_history.json",
    cwd="<skill_dir>"
)
```

> If `0a` was not executed or the user did not select, remove the
> `--python <selected_python>` argument.

Read `~/.qwenpaw/tmp/lang_detect.json` to confirm:
- **language**: target language (python/javascript/typescript/go/rust/java)
- **framework**: test framework (pytest/jest/vitest/go test/cargo nextest/maven)
- **toolchain**: whether toolchain is available, prompt user to install if missing
  - `python_path`: selected Python interpreter path (Python only, used in later steps)
- **tree_sitter**: whether tree-sitter deps are available (not needed for Python)
- **pytest_plugins**: pytest plugin detection (Python only)
  - `plugins`: plugin availability dict, key is package name (e.g. `pytest-mock`), value contains:
    - `available`: whether installed
    - `trigger_type`: trigger type (fixture/marker/decorator)
    - `trigger`: trigger identifier (e.g. `mocker`, `@pytest.mark.asyncio`)
    - `alt`: alternative approach
  - `asyncio_mode`: whether asyncio_mode is configured (auto/strict/empty)
  - `pytest_asyncio`: whether pytest-asyncio is installed (backward compat)
  - `anyio`: whether anyio is installed (backward compat)
  - `missing`: list of missing required plugins
  - `hints`: list of install hints
  - `hint`: install hint string (backward compat)

Must clear residual failure history before starting: `rm -f ~/.qwenpaw/failure_history.json`
(prevents stale data from previous sessions causing false `stop=true`)

**Plugin usage constraints** (Python):
- Only use plugins where `plugins[<package>].available=true`
- `pytest-mock` not available → use `unittest.mock.patch` / `MagicMock`
- `hypothesis` not available → use `@pytest.mark.parametrize`
- `pytest-benchmark` not available → use `time.perf_counter()` for manual timing
- `pytest-subtests` not available → use multiple independent test functions
- `pytest-freezegun` not available → use `freezegun.freeze_time()` or `unittest.mock.patch`
- `responses` not available → use `unittest.mock.patch` for requests

If toolchain or tree-sitter dependencies are missing, **inform the user**
what needs to be installed and wait for confirmation before continuing.

**Async test plugin note** (Python):
- If `pytest_plugins.missing` contains `pytest-asyncio`,
  **inform the user** to install: `pip install pytest-asyncio`
- Or in Step 3, use `@pytest.mark.anyio` if anyio is installed
- **Do NOT** use `@pytest.mark.asyncio` without pytest-asyncio installed,
  as it will cause all async tests to fail

Locating rules:
- User gave a file path → use directly
- User gave only a function name → use `grep_search` to find `def <name>` / `function <name>` in the project
- In Coding Mode → use the currently open file
- User gave a directory → recursively analyze all source files in it

### Step 1: AST Analysis

```bash
execute_shell_command(
    command="python3 <skill_dir>/scripts/analyze.py <target_path> --lang <lang> --output ~/.qwenpaw/tmp/analysis.json",
    cwd="<skill_dir>"
)
```

Read `~/.qwenpaw/tmp/analysis.json` to understand:
- Function signatures (args, type annotations, defaults)
- Branch node count (if/for/while/try/except/BoolOp)
- Import dependencies
- Complexity (cyclomatic complexity)
- Class and method structure

> Python uses the `ast` module (zero deps), other languages use tree-sitter.
> Adapters are dynamically discovered via `lang/*_lang.py`.

### Step 2: Case Design

```bash
execute_shell_command(
    command="python3 <skill_dir>/scripts/gen_cases.py --analysis-file ~/.qwenpaw/tmp/analysis.json --lang <lang> --output ~/.qwenpaw/tmp/cases.json",
    cwd="<skill_dir>"
)
```

Read `~/.qwenpaw/tmp/cases.json` to get a structured case list with four types:
- **equivalence_class**: normal values derived from type annotations
- **boundary_value**: boundary value table by parameter type
- **exception_path**: generated when branch count > 0
- **decision_table**: generated when branch count >= 3

> Case design algorithms are language-agnostic (`case_design.py`),
> TYPE_BOUNDARIES are injected per language.

### Step 3: Generate Test Code

Based on the case list, **you (the LLM)** generate test code. Rules:

#### General Rules
1. **Naming**: follow language conventions
2. **Parameterization**: use parametrization for same-type boundary values
3. **fixture/setup**: extract repeated setup logic into fixtures/setup
4. **mock**: use mock for external deps (network, filesystem, database)
5. **Exception assertions**: use language-idiomatic exception assertions
6. **import**: prefer standard imports, use language-idiomatic fallback if needed
7. **coverage goal**: every case list entry must have a corresponding test
8. **isolation**: no test-order dependencies, no global side effects

#### Per-language Idioms

**Python (pytest)**
- File naming: `test_<name>.py`, functions `test_<name>_<scenario>`
- Parametrize: `@pytest.mark.parametrize`
- Exceptions: `with pytest.raises(ExpectedError):`
- Mock: `unittest.mock.patch`
- Placement: `tests/` directory
- **Plugin usage** (check `pytest_plugins.plugins` in `~/.qwenpaw/tmp/lang_detect.json`):
  - `mocker` fixture not available → use `unittest.mock.patch` / `MagicMock`
  - `@given` not available → use `@pytest.mark.parametrize`
  - `benchmark` fixture not available → use `time.perf_counter()` for manual timing
  - `subtests` fixture not available → use multiple independent test functions
  - `freezer` fixture not available → use `freezegun.freeze_time()` or `unittest.mock.patch`
  - `@responses.activate` not available → use `unittest.mock.patch` for requests
- Async tests:
  - Check `pytest_plugins` field from `~/.qwenpaw/tmp/lang_detect.json`
  - `pytest_asyncio=true` → use `@pytest.mark.asyncio`
  - `pytest_asyncio=false` but `anyio=true` → use `@pytest.mark.anyio`
  - Both missing → **inform user to install first**, do not generate async tests

**JavaScript/TypeScript (Jest)**
- File naming: `<name>.test.js` / `<name>.test.ts` (colocated)
- Structure: `describe('Module', () => { it('should ...', () => {}) })`
- Assertions: `expect(result).toBe(expected)`
- Exceptions: `expect(() => fn()).toThrow(Error)`
- Mock: `jest.mock('module')` / `vi.mock('module')`
- Async: `async/await`, `expect(promise).resolves.toBe(x)`

**Go**
- File naming: `<name>_test.go` (same directory)
- Functions: `func TestName(t *testing.T)`
- Table-driven: `tests := []struct{...}{...}` + `for _, tt := range tests`
- Assertions: `if got != want { t.Errorf(...) }`
- Placement: same directory as source file

**Rust**
- File naming: `tests/<name>.rs` or `#[cfg(test)]` inline
- Functions: `#[test] fn test_name()`
- Assertions: `assert_eq!(got, want)` / `assert!(condition)`
- Exceptions: `#[should_panic(expected = "...")]`
- Placement: `tests/` directory or `mod tests` inline

**Java (JUnit)**
- File naming: `<Name>Test.java`, placement `src/test/java/`
- Methods: `@Test void testName()`
- Assertions: `assertEquals(expected, actual)`
- Exceptions: `assertThrows(ExpectedException.class, () -> ...)`
- Mock: `@Mock` + `Mockito.when()`

Use `write_file` to write test code into the project's test directory.

### Step 4: Execute Tests

Select command by language, output JUnit XML uniformly:

| Language | Command |
|----------|---------|
| Python | `<python_path> -m pytest <test_path> --junitxml=~/.qwenpaw/tmp/report.xml -v --tb=short` (when `toolchain.python_path` exists, use it instead of `python3`; otherwise fall back to `python3 -m pytest ...`) |
| JS/TS | `npx jest --reporters=junit --outputFile=~/.qwenpaw/tmp/report.xml <test_path>` |
| Go | `gotestsum --junitfile=~/.qwenpaw/tmp/report.xml -- <test_path>` |
| Rust | `cargo nextest run --junit-path=~/.qwenpaw/tmp/report.xml <test_path>` |
| Java | `mvn test -Dtest=<test_class> ; for f in target/surefire-reports/*.xml; do cp "$f" ~/.qwenpaw/tmp/report.xml; break; done 2>/dev/null; true` |

```bash
execute_shell_command(
    command="<test_command> 2>&1 | tail -200; true",
    cwd="<project_dir>"
)
```

Notes:
- `--junitxml` / `--outputFile` / `--junitfile` is required for the next step
- `2>&1 | tail -200` prevents overly long output
- `; true` ensures the shell command doesn't exit non-zero due to test failures
- `cwd` must be the project root so import paths resolve correctly

### Step 5: Parse Failures

```bash
execute_shell_command(
    command="python3 <skill_dir>/scripts/parse_failures.py --junitxml ~/.qwenpaw/tmp/report.xml --lang <lang> --history-file ~/.qwenpaw/failure_history.json --output ~/.qwenpaw/tmp/failures.json",
    cwd="<skill_dir>"
)
```

Read `~/.qwenpaw/tmp/failures.json` to get:
- **summary**: total, passed, failed, errors, build_errors, pass rate
- **failures**: each failure's category, severity, suggestion
- **all_cases**: status of all cases
- **stop**: whether repeated failure signature detected (`true` means should stop iterating)
- **repeat_count**: number of times the current failure signature has appeared

### Step 6: Analyze Failures

Decide how to handle based on the `severity` field:

| severity | meaning | handling |
|----------|---------|----------|
| `test_logic` | test code is wrong | fix test code |
| `test_setup` | test environment/config issue | fix conftest or fixture |
| `missing_plugin` | pytest plugin not installed | install plugin or use alternative |
| `target_bug` | likely source code bug | **do NOT modify source**, report to user |
| `test_env` | runtime environment issue | check dependencies, paths, permissions |
| `build_error` | compiled language build failure | fix compilation errors and rebuild |

### Step 7: Auto-fix and Iterate (max 2 rounds)

1. **Check `stop` field**: if `stop=true` in `~/.qwenpaw/tmp/failures.json`, the failure
   signature is the same as the previous round (same tests failing the same way).
   **Stop iterating immediately** and report to the user
2. For `test_logic` / `test_setup` / `missing_plugin` failures, use `edit_file`
   to fix test code (for `missing_plugin`, install the plugin or use alternative)
3. For `build_error` failures, fix compilation errors (syntax/type/dependency)
4. Re-run Step 4-5 (in round 2, only run last-failed tests for faster iteration)
5. Repeat until all pass, or reach the **2-round limit**
6. If failures remain after 2 rounds → stop and report to user

**Hard rules:**
- **When `stop=true`, must stop iterating** — do not fix tests further, report to user
- **Do NOT modify target code** (source files), only fix test code
- Suspected `target_bug` failures → report to user, let them decide
- Do NOT delete test cases just to "make tests pass"

## Output Report

After the flow completes, report to the user:
1. **Language detection**: detected language, framework, toolchain status
2. **Analysis summary**: which files were analyzed, how many functions/classes
3. **Generated tests**: how many cases, which types covered
4. **Execution results**: pass rate, failure count, compilation error count
5. **Iteration rounds**: how many fix rounds were done
6. **Remaining failures** (if any): listed by severity with suggestions
7. **Suspected bugs** (if any): `target_bug` failures flagged for user confirmation

## Multi-language Architecture

Three-layer architecture design:
- **Layer 1 AST Analysis**: Python uses `ast` module (zero deps), other languages use tree-sitter packages
- **Layer 2 Case Design**: language-agnostic shared algorithms (`case_design.py`)
- **Layer 3 Language Adaptation**: test commands, failure rules, file placement (`registry.py`)

`lang/` directory dynamically discovers adapters:
- `lang/__init__.py` — register decorator + get_analyzer dispatch + dynamic `*_lang.py` scanning
- `lang/base.py` — BaseAnalyzer abstract base class
- `lang/case_design.py` — four case design shared algorithms
- `lang/registry.py` — language → command/rules/file placement mapping
- `lang/python_lang.py` — Python adapter (`ast` module, zero deps)
- `lang/javascript_lang.py` — JavaScript adapter (tree-sitter-javascript)
- `lang/typescript_lang.py` — TypeScript adapter (tree-sitter-typescript)
- `lang/go_lang.py` — Go adapter (tree-sitter-go)
- `lang/rust_lang.py` — Rust adapter (tree-sitter-rust)
- `lang/java_lang.py` — Java adapter (tree-sitter-java)
- To add a new language: create `lang/<lang>_lang.py`, implement `analyze`/`gen_cases`, register with `@register`

> Non-Python languages require the corresponding tree-sitter package (see `scripts/requirements.txt`).
> The `tree_sitter` field in `detect_lang.py` checks whether the dependency is available and prompts for installation if missing.
> A single adapter failing to load does not affect other adapters (`__init__.py` has try/except error isolation).
