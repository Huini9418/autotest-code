"""语言注册表：语言 -> 测试命令 / 失败规则 / 文件放置。

每语言适配器只需在 ``__init__.py`` 中通过 ``@register`` 注册 analyzer
类，命令/规则/文件放置等元数据声明在此文件中，实现数据与行为分离。
"""

# 语言 -> 测试执行命令
# {test_path} 占位测试路径，{report} 占位 JUnit XML 输出路径
TEST_COMMANDS: dict[str, dict] = {
    "python": {
        "framework": "pytest",
        "command": (
            "python3 -m pytest {test_path} "
            "--junitxml={report} -v --tb=short"
        ),
        "report_format": "junit_xml",
        "needs_build": False,
    },
    "javascript": {
        "framework": "jest",
        "command": (
            "npx jest --reporters=junit "
            "--outputFile={report} {test_path}"
        ),
        "report_format": "junit_xml",
        "needs_build": False,
    },
    "typescript": {
        "framework": "jest",
        "command": (
            "npx jest --reporters=junit "
            "--outputFile={report} {test_path}"
        ),
        "report_format": "junit_xml",
        "needs_build": False,
    },
    "go": {
        "framework": "go test",
        "command": (
            "gotestsum --junitfile={report} -- {test_path}"
        ),
        "report_format": "junit_xml",
        "needs_build": False,
    },
    "rust": {
        "framework": "cargo nextest",
        "command": (
            "cargo nextest run --junit-path={report} {test_path}"
        ),
        "report_format": "junit_xml",
        "needs_build": True,
    },
    "java": {
        "framework": "maven",
        # Maven -Dtest 期望类名而非文件路径，用 {test_class} 占位
        # 用 ; 而非 && 确保测试失败时仍复制报告
        # 只复制第一个 XML 文件到 {report}
        "command": (
            "mvn test -Dtest={test_class} "
            "; for f in target/surefire-reports/*.xml; "
            "do cp \"$f\" {report}; break; done 2>/dev/null; true"
        ),
        "report_format": "surefire",
        "needs_build": True,
    },
}

# 语言 -> 测试文件放置规则
# colocated=True 表示测试文件与源文件同目录
FILE_PLACEMENT: dict[str, dict] = {
    "python": {
        "directory": "tests/",
        "naming": "test_{name}.py",
        "colocated": False,
        "test_dir_pattern": "tests/",
    },
    "javascript": {
        "directory": "",
        "naming": "{name}.test.js",
        "colocated": True,
        "test_dir_pattern": "__tests__/",
    },
    "typescript": {
        "directory": "",
        "naming": "{name}.test.ts",
        "colocated": True,
        "test_dir_pattern": "__tests__/",
    },
    "go": {
        "directory": "",
        "naming": "{name}_test.go",
        "colocated": True,
        "test_dir_pattern": "",
    },
    "rust": {
        "directory": "tests/",
        "naming": "{name}.rs",
        "colocated": False,
        "test_dir_pattern": "tests/",
    },
    "java": {
        "directory": "src/test/java/",
        "naming": "{name}Test.java",
        "colocated": False,
        "test_dir_pattern": "src/test/java/",
    },
}

# 语言 -> 失败分类规则
# (pattern, category, severity)
# severity: test_logic / test_setup / target_bug / test_env / build_error
FAILURE_RULES: dict[str, list[tuple[str, str, str]]] = {
    "python": [
        (r"AssertionError|Assertion failed|assert ", "assertion_error",
         "test_logic"),
        (r"ImportError|ModuleNotFoundError", "import_error", "test_setup"),
        (r"PluginNotFoundError|plugin .* could not be found",
         "missing_plugin", "test_setup"),
        (r"fixture 'mocker' not found|fixture 'benchmark' not found|"
         r"fixture 'subtests' not found|fixture 'freezer' not found",
         "missing_plugin", "test_setup"),
        (r"TypeError|type object is not", "type_error", "test_logic"),
        (r"ValueError", "value_error", "test_logic"),
        (r"KeyError", "key_error", "test_logic"),
        (r"AttributeError", "attribute_error", "test_logic"),
        (r"FileNotFoundError|FileExistsError|PermissionError|OSError",
         "file_error", "test_env"),
        (r"fixture .* not found|error in fixture|fixture setup",
         "fixture_error", "test_setup"),
        (r"collection error|Error collecting|errors during collection",
         "collection_error", "test_setup"),
        (r"TimeoutError|timed out|deadline", "timeout", "test_env"),
        (r"SyntaxError|IndentationError", "syntax_error", "test_logic"),
        (r"NameError|UnboundLocalError", "name_error", "test_logic"),
        (r"RuntimeError|RecursionError", "runtime_error", "target_bug"),
        (r"ZeroDivisionError", "zero_division", "target_bug"),
        (r"IndexError", "index_error", "target_bug"),
        (r"StopIteration", "stop_iteration", "target_bug"),
    ],
    "javascript": [
        (r"AssertionError|expect\(.*\)\.toBe|assert ", "assertion_error",
         "test_logic"),
        (r"TypeError:|is not a function|is not defined", "type_error",
         "test_logic"),
        (r"ReferenceError: .* is not defined", "reference_error",
         "test_logic"),
        (r"SyntaxError: Unexpected", "syntax_error", "test_logic"),
        (r"Cannot find module|MODULE_NOT_FOUND", "import_error",
         "test_setup"),
        (r"ENOENT|no such file or directory", "file_error", "test_env"),
        (r"timeout|timed out|exceeded", "timeout", "test_env"),
        (r"Network Error|ECONNREFUSED|ECONNRESET", "network_error",
         "test_env"),
        (r"RangeError: Maximum call stack", "range_error", "target_bug"),
        (r"JSON\.parse:|Unexpected token", "json_error", "test_logic"),
    ],
    "typescript": [
        (r"AssertionError|expect\(.*\)\.toBe|assert ", "assertion_error",
         "test_logic"),
        (r"TypeError:|is not a function|is not defined", "type_error",
         "test_logic"),
        (r"ReferenceError: .* is not defined", "reference_error",
         "test_logic"),
        (r"SyntaxError: Unexpected|TS\d+: ", "syntax_error", "test_logic"),
        (r"Cannot find module|MODULE_NOT_FOUND", "import_error",
         "test_setup"),
        (r"ENOENT|no such file or directory", "file_error", "test_env"),
        (r"timeout|timed out|exceeded", "timeout", "test_env"),
        (r"Type .* is not assignable", "type_mismatch", "test_logic"),
        (r"Property .* does not exist", "property_error", "test_logic"),
        (r"RangeError: Maximum call stack", "range_error", "target_bug"),
    ],
    "go": [
        (r"Error Trace|--- FAIL", "assertion_error", "test_logic"),
        (r"panic: runtime error", "panic", "target_bug"),
        (r"nil pointer dereference", "nil_pointer", "target_bug"),
        (r"goroutine.* \[running\]", "goroutine_error", "target_bug"),
        (r"cannot find package|undefined:", "import_error", "test_setup"),
        (r"syntax error|expected", "syntax_error", "test_logic"),
        (r"timeout|context deadline exceeded", "timeout", "test_env"),
        (r"no such file or directory|open.*: no such file",
         "file_error", "test_env"),
        (r"connection refused|dial tcp", "network_error", "test_env"),
    ],
    "rust": [
        (r"assertion .* failed|panicked at", "assertion_error",
         "test_logic"),
        (r"called .Option::unwrap. on a None value", "unwrap_none",
         "target_bug"),
        (r"called .Result::unwrap. on an Err value", "unwrap_err",
         "target_bug"),
        (r"index out of bounds", "index_error", "target_bug"),
        (r"cannot find .* in this scope|unresolved import",
         "import_error", "test_setup"),
        (r"expected.*found", "syntax_error", "test_logic"),
        (r"mismatched types|expected.*got", "type_error", "test_logic"),
        (r"borrowed.*does not live long enough", "lifetime_error",
         "test_logic"),
        (r"timeout|timed out", "timeout", "test_env"),
        (r"no such file or directory", "file_error", "test_env"),
    ],
    "java": [
        (r"org\.junit\.|AssertionError|assert ", "assertion_error",
         "test_logic"),
        (r"java\.lang\.NullPointerException", "null_pointer",
         "target_bug"),
        (r"java\.lang\.ClassNotFoundException", "class_not_found",
         "test_setup"),
        (r"java\.lang\.IllegalArgumentException", "illegal_argument",
         "test_logic"),
        (r"java\.lang\.IndexOutOfBoundsException|ArrayIndexOutOfBoundsException",
         "index_error", "target_bug"),
        (r"java\.io\.IOException|FileNotFoundException", "io_error",
         "test_env"),
        (r"java\.lang\.InterruptedException|timeout", "timeout",
         "test_env"),
        (r"java\.lang\.StackOverflowError", "stack_overflow", "target_bug"),
        (r"NoSuchElementException", "no_such_element", "target_bug"),
        (r"java\.lang\.ClassCastException", "class_cast", "test_logic"),
        (r"COMPILATION ERROR|BUILD FAILURE|cannot find symbol",
         "compilation_error", "build_error"),
        (r"java\.lang\.OutOfMemoryError", "out_of_memory", "test_env"),
    ],
}

# 编译型语言构建失败规则（build_error severity）
BUILD_ERROR_RULES: list[tuple[str, str]] = [
    (r"COMPILATION ERROR|BUILD FAILURE", "compilation_error"),
    (r"error: expected|error: unterminated|error: unmatched",
     "syntax_build_error"),
    # Rust: 实际格式是 error[E0308]:（无空格）
    (r"error\[E\d+\]", "rust_compile_error"),
    # Java: xxx.java:行号: error:
    (r"\.java:\d+: error:", "java_compile_error"),
    # TS: tsc 编译错误
    (r"error TS\d+:|Failed to compile", "ts_compile_error"),
]

# pytest 插件声明：包名 -> 元数据
# trigger_type 说明：
#   - "fixture": 失败消息为 "fixture 'X' not found"，由 missing_plugin 规则捕获
#   - "marker" / "decorator": 失败消息为 ImportError/ModuleNotFoundError，
#     由 import_error 规则捕获，error_pattern 用于 _suggest() 匹配
PYTEST_PLUGINS: dict[str, dict] = {
    "pytest-asyncio": {
        "import_name": "pytest_asyncio",
        "trigger_type": "marker",
        "trigger": "@pytest.mark.asyncio",
        "error_pattern": r"asyncio_mode|pytest\.mark\.asyncio",
        "alt": "使用 @pytest.mark.anyio（需 anyio）或改用同步测试",
    },
    "anyio": {
        "import_name": "anyio",
        "trigger_type": "marker",
        "trigger": "@pytest.mark.anyio",
        "error_pattern": r"pytest\.mark\.anyio",
        "alt": "使用 @pytest.mark.asyncio（需 pytest-asyncio）或改用同步测试",
    },
    "pytest-mock": {
        "import_name": "pytest_mock",
        "trigger_type": "fixture",
        "trigger": "mocker",
        "error_pattern": r"fixture 'mocker' not found",
        "alt": "使用 unittest.mock.patch / MagicMock",
    },
    "hypothesis": {
        "import_name": "hypothesis",
        "trigger_type": "decorator",
        "trigger": "@given",
        "error_pattern": r"@given|NameError: name 'given'",
        "alt": "使用 @pytest.mark.parametrize 参数化测试",
    },
    "pytest-benchmark": {
        "import_name": "pytest_benchmark",
        "trigger_type": "fixture",
        "trigger": "benchmark",
        "error_pattern": r"fixture 'benchmark' not found",
        "alt": "使用 time.perf_counter() 手动计时",
    },
    "pytest-subtests": {
        "import_name": "pytest_subtests",
        "trigger_type": "fixture",
        "trigger": "subtests",
        "error_pattern": r"fixture 'subtests' not found",
        "alt": "使用多个独立测试函数",
    },
    "pytest-freezegun": {
        "import_name": "pytest_freezegun",
        "trigger_type": "fixture",
        "trigger": "freezer",
        "error_pattern": r"fixture 'freezer' not found",
        "alt": "使用 freezegun.freeze_time() 或 unittest.mock.patch 对 datetime 打补丁",
    },
    "responses": {
        "import_name": "responses",
        "trigger_type": "decorator",
        "trigger": "@responses.activate",
        "error_pattern": r"responses\.activate|NameError: name 'responses'",
        "alt": "使用 unittest.mock.patch 对 requests 打补丁",
    },
}


def get_test_command(lang: str) -> dict:
    """返回语言的测试执行命令配置。"""
    return TEST_COMMANDS.get(lang, {})


def get_failure_rules(lang: str) -> list[tuple[str, str, str]]:
    """返回语言的失败分类规则列表。"""
    return FAILURE_RULES.get(lang, [])


def get_file_placement(lang: str) -> dict:
    """返回语言的测试文件放置规则。"""
    return FILE_PLACEMENT.get(lang, {})


def get_build_error_rules() -> list[tuple[str, str]]:
    """返回编译型语言构建失败的通用规则。"""
    return BUILD_ERROR_RULES


def get_pytest_plugins() -> dict[str, dict]:
    """返回 pytest 插件声明表。"""
    return PYTEST_PLUGINS
