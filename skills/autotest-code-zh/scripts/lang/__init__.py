"""语言分析器注册与分发。

动态发现 ``lang/*_lang.py`` 文件并自动注册，新增语言只需加文件
无需修改入口脚本。

用法::

    from lang import get_analyzer, list_languages
    from lang import get_test_command, get_failure_rules, get_file_placement

    analyzer = get_analyzer("python")
    result = analyzer.analyze("/path/to/source.py")
"""

import importlib
import pkgutil

# lang_name -> analyzer 实例
LANGUAGES: dict[str, object] = {}


def register(lang_name: str):
    """装饰器：注册一个语言分析器类。

    用法::

        @register("python")
        class PythonAnalyzer(BaseAnalyzer):
            ...
    """

    def deco(cls):
        LANGUAGES[lang_name] = cls()
        return cls

    return deco


def get_analyzer(lang: str):
    """获取指定语言的分析器实例。"""
    if lang not in LANGUAGES:
        raise ValueError(
            f"Unsupported language: {lang}. "
            f"Supported: {list(LANGUAGES.keys())}"
        )
    return LANGUAGES[lang]


def list_languages() -> list[str]:
    """返回已注册的语言列表。"""
    return list(LANGUAGES.keys())


def get_test_command(lang: str) -> dict:
    """返回语言的测试执行命令配置。"""
    from .registry import TEST_COMMANDS

    return TEST_COMMANDS.get(lang, {})


def get_failure_rules(lang: str) -> list[tuple[str, str, str]]:
    """返回语言的失败分类规则列表。"""
    from .registry import FAILURE_RULES

    return FAILURE_RULES.get(lang, [])


def get_file_placement(lang: str) -> dict:
    """返回语言的测试文件放置规则。"""
    from .registry import FILE_PLACEMENT

    return FILE_PLACEMENT.get(lang, {})


def get_build_error_rules() -> list[tuple[str, str]]:
    """返回编译型语言构建失败的通用规则。"""
    from .registry import BUILD_ERROR_RULES

    return BUILD_ERROR_RULES


def get_pytest_plugins() -> dict[str, dict]:
    """返回 pytest 插件声明表。"""
    from .registry import PYTEST_PLUGINS

    return PYTEST_PLUGINS


def _discover_languages():
    """动态扫描 lang/*_lang.py 并 import，触发 @register 注册。

    单个适配器 import 失败不会影响其他适配器。
    """
    for _, name, _ in pkgutil.iter_modules(__path__):
        if name.endswith("_lang") and name != "base_lang":
            try:
                importlib.import_module(f".{name}", package=__name__)
            except Exception as e:
                # 打印警告但继续加载其他适配器
                import warnings

                warnings.warn(
                    f"Failed to load language adapter '{name}': {e}",
                    ImportWarning,
                    stacklevel=2,
                )


# 模块加载时自动发现所有语言适配器
_discover_languages()
