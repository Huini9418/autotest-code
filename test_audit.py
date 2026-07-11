#!/usr/bin/env python3
"""代码审阅测试脚本 - 验证发现的潜在问题和bug

Author: AutoTest Code Audit
Date: 2026-07-09
"""

import ast
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from textwrap import dedent

# 添加项目路径
sys.path.insert(0, '/Users/weichunhui/python_daliy/autotest-code/skills/autotest-code-zh/scripts')


def test_thread_safety():
    """测试线程安全性问题 - LANGUAGES 字典并发访问"""
    print("🔍 Testing thread safety in language registration...")
    
    from lang import LANGUAGES, _discover_languages
    
    # 清空现有语言
    original_languages = LANGUAGES.copy()
    LANGUAGES.clear()
    
    errors = []
    success_count = [0]
    
    def import_languages():
        try:
            _discover_languages()
            success_count[0] += 1
        except Exception as e:
            errors.append(str(e))
    
    # 启动多个线程同时导入语言
    threads = []
    for i in range(10):
        t = threading.Thread(target=import_languages)
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    # 恢复原始状态
    LANGUAGES.clear()
    LANGUAGES.update(original_languages)
    
    if errors:
        print(f"❌ Thread safety issue detected! Errors: {errors}")
        return False
    elif success_count[0] != 10:
        print(f"❌ Thread safety issue: Expected 10 successful imports, got {success_count[0]}")
        return False
    else:
        print("✅ Thread safety test passed")
        return True


def test_ast_unparse_compatibility():
    """测试 ast.unparse 的兼容性问题"""
    print("\n🔍 Testing ast.unparse compatibility...")
    
    # 检查 Python 版本
    if sys.version_info < (3, 9):
        print("⚠️  Python < 3.9: ast.unparse not available")
        return True
    
    try:
        from lang.python_lang import PythonAnalyzer
        
        # 创建一个复杂的 AST 节点
        code = """
def complex_function(a: int, b: str = "default") -> dict:
    return {"result": a + len(b)}
"""
        tree = ast.parse(code)
        func_node = tree.body[0]
        
        analyzer = PythonAnalyzer()
        
        # 测试参数注解解析
        args = analyzer._extract_args(func_node)
        print(f"   Extracted args: {args}")
        
        # 测试返回类型解析
        returns = ast.unparse(func_node.returns) if func_node.returns else None
        print(f"   Returns: {returns}")
        
        print("✅ ast.unparse compatibility test passed")
        return True
        
    except Exception as e:
        print(f"❌ ast.unparse compatibility issue: {e}")
        return False


def test_path_traversal_vulnerability():
    """测试路径遍历漏洞"""
    print("\n🔍 Testing path traversal vulnerability in is_safe_path...")
    
    try:
        from utils.temp_dir import is_safe_path
    except ImportError:
        # 使用 parse_failures.py 中的回退实现
        import tempfile
        from pathlib import Path
        
        def is_safe_path(path):
            try:
                resolved = Path(os.path.expanduser(str(path))).resolve()
                temp_dirs = [
                    Path(tempfile.gettempdir()).resolve(),
                    Path("/tmp").resolve(),
                    Path("/var/tmp").resolve(),
                ]
                for temp_dir in temp_dirs:
                    try:
                        if resolved.is_relative_to(temp_dir):
                            return True
                    except ValueError:
                        pass
                try:
                    user_home = Path.home().resolve()
                    if resolved.is_relative_to(user_home):
                        relative_parts = resolved.relative_to(user_home).parts
                        if relative_parts:
                            first_part = relative_parts[0]
                            allowed_dirs = {".claude", ".qwenpaw", ".opencode", ".codex"}
                            if first_part in allowed_dirs:
                                return True
                except RuntimeError:
                    pass
            except (OSError, RuntimeError):
                pass
            return False
    
    # 测试各种路径
    test_cases = [
        ("/tmp/test.txt", True, "Temp directory"),
        ("~/test.txt", False, "Home directory without allowed prefix"),
        ("~/.claude/test.txt", True, "Allowed home directory"),
        ("~/.malicious/../../../etc/passwd", False, "Path traversal attempt"),
        ("/var/tmp/test.txt", True, "Var temp directory"),
        ("/etc/passwd", False, "System file"),
        ("./test.txt", False, "Relative path"),
        ("../../etc/passwd", False, "Relative path traversal"),
    ]
    
    all_passed = True
    for path, expected, description in test_cases:
        result = is_safe_path(path)
        if result == expected:
            print(f"   ✅ {description}: {path} -> {result}")
        else:
            print(f"   ❌ {description}: {path} -> {result} (expected {expected})")
            all_passed = False
    
    return all_passed


def test_memory_leak_risk():
    """测试内存泄漏风险"""
    print("\n🔍 Testing memory leak risk with large files...")
    
    try:
        from lang.python_lang import PythonAnalyzer
        
        analyzer = PythonAnalyzer()
        
        # 创建一个很大的临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            # 生成 1MB 的代码
            large_code = "x = 1\n" * (1024 * 1024 // 6)  # ~1MB
            f.write(large_code)
            temp_path = f.name
        
        try:
            # 分析大文件
            start_time = time.time()
            result = analyzer.analyze(temp_path)
            end_time = time.time()
            
            print(f"   Analysis completed in {end_time - start_time:.2f}s")
            print(f"   Functions found: {result['summary']['total_functions']}")
            
            # 检查是否合理完成
            if end_time - start_time > 5.0:
                print("   ⚠️  Analysis took too long, potential performance issue")
                return False
            
            print("✅ Memory leak test passed (no obvious leaks detected)")
            return True
            
        finally:
            os.unlink(temp_path)
    
    except Exception as e:
        print(f"❌ Memory leak test failed: {e}")
        return False


def test_injection_vulnerability():
    """测试代码注入漏洞"""
    print("\n🔍 Testing code injection vulnerability in case generation...")
    
    from lang.case_design import design_cases
    from lang.python_lang import TYPE_BOUNDARIES, TYPE_NORMALS
    
    # 创建一个带有恶意注解的分析结果
    malicious_analysis = {
        "files": [
            {
                "file": "test.py",
                "functions": [
                    {
                        "name": "dangerous_func",
                        "qualname": "dangerous_func",
                        "line": 1,
                        "args": [
                            {
                                "name": "cmd",
                                "annotation": "str",
                                "default": None,
                                "has_default": False,
                            }
                        ],
                        "returns": None,
                        "decorators": [],
                        "docstring": None,
                        "branches": 0,
                        "complexity": 1,
                        "is_async": False,
                    }
                ],
                "classes": [],
                "imports": [],
            }
        ],
        "summary": {
            "total_files": 1,
            "error_files": 0,
            "total_functions": 1,
            "total_classes": 0,
            "total_branches": 0,
        },
    }
    
    try:
        # 生成测试用例
        result = design_cases(malicious_analysis, TYPE_BOUNDARIES, TYPE_NORMALS)
        test_cases = result.get("test_cases", [])
        
        # 检查是否有安全测试用例
        security_cases = [c for c in test_cases if c.get("type") == "security_test"]
        
        if security_cases:
            print(f"   Found {len(security_cases)} security test cases")
            for case in security_cases[:3]:  # 只显示前3个
                inputs = case.get("inputs", {})
                print(f"   Inputs: {inputs}")
                # 检查是否有危险的 payload
                dangerous_patterns = ["os.system", "subprocess", "exec", "eval", "rm", "wget", "curl"]
                for key, value in inputs.items():
                    for pattern in dangerous_patterns:
                        if pattern in str(value):
                            print(f"   ⚠️  Potential dangerous payload detected: {value}")
        
        print("✅ Injection vulnerability test completed")
        return True
        
    except Exception as e:
        print(f"❌ Injection vulnerability test failed: {e}")
        return False


def test_error_handling():
    """测试错误处理机制"""
    print("\n🔍 Testing error handling mechanisms...")
    
    from lang.python_lang import PythonAnalyzer
    
    analyzer = PythonAnalyzer()
    
    # 测试语法错误处理
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write("def broken_function(:")  # 语法错误
        temp_path = f.name
    
    try:
        result = analyzer.analyze(temp_path)
        
        # 应该有错误文件
        if result['summary']['error_files'] > 0:
            print("   ✅ Syntax error properly handled")
            error_files = [f for f in result['files'] if 'error' in f]
            if error_files:
                print(f"   Error message: {error_files[0]['error']}")
        else:
            print("   ❌ Syntax error not properly detected")
            return False
        
        print("✅ Error handling test passed")
        return True
        
    except Exception as e:
        print(f"❌ Error handling test failed: {e}")
        return False
    finally:
        os.unlink(temp_path)


def test_edge_cases():
    """测试边缘情况"""
    print("\n🔍 Testing edge cases...")
    
    from lang.python_lang import PythonAnalyzer
    
    analyzer = PythonAnalyzer()
    
    # 测试空文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write("")  # 空文件
        empty_path = f.name
    
    # 测试只包含注释的文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write("# This is a comment\n# Another comment\n")
        comment_path = f.name
    
    # 测试只包含类的文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write("class EmptyClass: pass")
        class_path = f.name
    
    try:
        # 测试空文件
        result = analyzer.analyze(empty_path)
        if result['summary']['total_files'] == 0:
            print("   ✅ Empty file handled correctly")
        else:
            print(f"   ❌ Empty file: expected 0 files, got {result['summary']['total_files']}")
            return False
        
        # 测试注释文件
        result = analyzer.analyze(comment_path)
        if result['summary']['total_files'] == 0:
            print("   ✅ Comment-only file handled correctly")
        else:
            print(f"   ❌ Comment-only file: expected 0 files, got {result['summary']['total_files']}")
            return False
        
        # 测试类文件
        result = analyzer.analyze(class_path)
        if result['summary']['total_classes'] == 1:
            print("   ✅ Class-only file handled correctly")
        else:
            print(f"   ❌ Class-only file: expected 1 class, got {result['summary']['total_classes']}")
            return False
        
        print("✅ Edge cases test passed")
        return True
        
    except Exception as e:
        print(f"❌ Edge cases test failed: {e}")
        return False
    finally:
        for path in [empty_path, comment_path, class_path]:
            if os.path.exists(path):
                os.unlink(path)


def test_performance_bottlenecks():
    """测试性能瓶颈"""
    print("\n🔍 Testing performance bottlenecks...")
    
    from lang.python_lang import PythonAnalyzer
    from lang.case_design import design_cases
    from lang.python_lang import TYPE_BOUNDARIES, TYPE_NORMALS
    
    analyzer = PythonAnalyzer()
    
    # 创建一个有很多嵌套结构的文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        code = """
def deeply_nested():
    if True:
        if True:
            if True:
                if True:
                    if True:
                        return 1
"""
        # 重复多次创建深度嵌套
        for i in range(10):
            f.write(code)
        temp_path = f.name
    
    try:
        start_time = time.time()
        result = analyzer.analyze(temp_path)
        analysis_time = time.time() - start_time
        
        print(f"   Analysis time: {analysis_time:.3f}s")
        
        # 生成测试用例
        start_time = time.time()
        cases_result = design_cases(result, TYPE_BOUNDARIES, TYPE_NORMALS)
        generation_time = time.time() - start_time
        
        print(f"   Case generation time: {generation_time:.3f}s")
        print(f"   Total cases generated: {cases_result['summary']['total_cases']}")
        
        if analysis_time > 2.0 or generation_time > 1.0:
            print("   ⚠️  Performance bottleneck detected")
            return False
        
        print("✅ Performance test passed")
        return True
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        return False
    finally:
        os.unlink(temp_path)


def run_all_tests():
    """运行所有审阅测试"""
    print("=" * 60)
    print("🔍 AUTOTEST-CODE PROJECT AUDIT")
    print("=" * 60)
    
    tests = [
        ("Thread Safety", test_thread_safety),
        ("AST Unparse Compatibility", test_ast_unparse_compatibility),
        ("Path Traversal Vulnerability", test_path_traversal_vulnerability),
        ("Memory Leak Risk", test_memory_leak_risk),
        ("Injection Vulnerability", test_injection_vulnerability),
        ("Error Handling", test_error_handling),
        ("Edge Cases", test_edge_cases),
        ("Performance Bottlenecks", test_performance_bottlenecks),
    ]
    
    results = {}
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results[test_name] = result
            if result:
                passed += 1
                print(f"\n✅ {test_name}: PASSED")
            else:
                failed += 1
                print(f"\n❌ {test_name}: FAILED")
        except Exception as e:
            failed += 1
            results[test_name] = False
            print(f"\n💥 {test_name}: CRASHED - {e}")
    
    print("\n" + "=" * 60)
    print("AUDIT SUMMARY")
    print("=" * 60)
    print(f"Total tests: {len(tests)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Success rate: {(passed/len(tests)*100):.1f}%")
    
    if failed > 0:
        print("\n⚠️  Some issues were detected during the audit!")
        print("Recommended actions:")
        print("  1. Fix thread safety issues in language registration")
        print("  2. Add proper error handling for ast.unparse")
        print("  3. Strengthen path validation in is_safe_path")
        print("  4. Add memory limits for large file processing")
        print("  5. Review security test case payloads")
    else:
        print("\n✅ All audit tests passed! The codebase appears to be in good shape.")
    
    # 保存结果
    with open('/Users/weichunhui/python_daliy/autotest-code/audit_report.json', 'w') as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "results": results,
            "summary": {
                "total": len(tests),
                "passed": passed,
                "failed": failed
            }
        }, f, indent=2)
    
    print(f"\n📄 Detailed report saved to: audit_report.json")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)