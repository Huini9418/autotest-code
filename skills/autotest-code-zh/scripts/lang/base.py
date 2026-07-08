"""BaseAnalyzer 抽象基类。

每个语言适配器继承此类，实现 ``analyze`` 和 ``gen_cases`` 方法。
返回结构遵循统一 schema，使上层入口脚本语言无关。
"""

from abc import ABC, abstractmethod


class BaseAnalyzer(ABC):
    """语言分析器抽象基类。

    子类必须实现:
        - analyze(target_path) -> dict
        - gen_cases(analysis) -> dict

    可选覆盖:
        - TYPE_BOUNDARIES: 类型 -> 边界值列表
        - TYPE_NORMALS: 类型 -> 正常值列表
    """

    TYPE_BOUNDARIES: dict = {}
    TYPE_NORMALS: dict = {}

    @abstractmethod
    def analyze(self, target_path: str) -> dict:
        """AST 分析：提取函数签名、分支、依赖、复杂度。

        返回结构::

            {
                "files": [
                    {
                        "file": "/path/to/source.py",
                        "functions": [
                            {
                                "name": "func_name",
                                "qualname": "ClassName.method_name",
                                "line": 10,
                                "args": [
                                    {
                                        "name": "x",
                                        "annotation": "int",
                                        "default": None,
                                        "has_default": False,
                                    }
                                ],
                                "returns": "bool",
                                "decorators": ["@staticmethod"],
                                "docstring": "...",
                                "branches": 3,
                                "complexity": 4,
                                "is_async": False,
                            }
                        ],
                        "classes": [
                            {
                                "name": "MyClass",
                                "line": 5,
                                "methods": [...],  # 同 functions 结构
                                "bases": ["BaseClass"],
                                "docstring": "...",
                            }
                        ],
                        "imports": ["import os", "from typing import List"],
                    }
                ],
                "summary": {
                    "total_files": 1,
                    "error_files": 0,
                    "total_functions": 3,
                    "total_classes": 1,
                    "total_branches": 5,
                }
            }
        """
        ...

    @abstractmethod
    def gen_cases(self, analysis: dict) -> dict:
        """基于分析结果生成测试用例清单。

        返回结构::

            {
                "test_cases": [
                    {
                        "target": "func_name",
                        "file": "/path/to/source.py",
                        "type": "equivalence_class",
                        "description": "func_name 正常输入等价类",
                        "inputs": {"x": "42"},
                        "expected": "正常返回，不抛出异常",
                    }
                ],
                "summary": {
                    "total_cases": 5,
                    "by_type": {
                        "equivalence_class": 1,
                        "boundary_value": 3,
                        "exception_path": 1
                    }
                }
            }
        """
        ...
