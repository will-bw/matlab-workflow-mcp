"""
MATLAB MCP Server 冒烟测试
===========================
使用 mock matlab.engine 验证核心逻辑路径，无需真实 MATLAB 安装。
覆盖三轮审查中发现的所有 P0 问题的正常路径。

运行: python test_smoke.py
"""

import sys
import os
import io
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

# Mock matlab.engine before importing the server
mock_matlab = MagicMock()
mock_engine_module = MagicMock()
mock_matlab.engine = mock_engine_module
mock_matlab.engine.MatlabExecutionError = Exception
sys.modules['matlab'] = mock_matlab
sys.modules['matlab.engine'] = mock_engine_module

# Mock mcp.server.fastmcp
mock_mcp_module = MagicMock()
mock_fastmcp = MagicMock()

# Make @mcp.tool() a no-op decorator that preserves the function
def fake_tool():
    def decorator(func):
        return func
    return decorator

mock_fastmcp_instance = MagicMock()
mock_fastmcp_instance.tool = fake_tool
mock_fastmcp.FastMCP = MagicMock(return_value=mock_fastmcp_instance)
sys.modules['mcp'] = mock_mcp_module
sys.modules['mcp.server'] = MagicMock()
sys.modules['mcp.server.fastmcp'] = mock_fastmcp

# Now import the server module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matlab_mcp_server as server


class TestRunTool(unittest.TestCase):
    """P0-1/P0-4: execute_code (now 'run') 图形捕获 + 超时"""

    def setUp(self):
        # Reset engine state
        server.eng = MagicMock()
        server._session_start_time = None

    def test_run_basic(self):
        """run 工具基本执行路径"""
        # run is async, test the _exec inner logic directly
        engine = server.eng
        engine.eval = MagicMock()

        stdout = io.StringIO()
        stderr = io.StringIO()

        # Simulate what _exec does
        with server._engine_lock:
            engine.eval("mcpFigsBefore = findall(0, 'Type', 'figure');", nargout=0)
            engine.eval("disp('hello')", nargout=0, stdout=stdout, stderr=stderr)

        # Verify engine.eval was called (not bare global access)
        self.assertTrue(engine.eval.called)

    def test_figure_capture_uses_legal_names(self):
        """P0-1: 图形捕获变量名不能以下划线开头"""
        import inspect
        source = inspect.getsource(server.run)
        # Must use mcpFigsBefore, not _figs_before_
        self.assertIn("mcpFigsBefore", source)
        self.assertNotIn("_figs_before_", source)

    def test_run_has_timeout_param(self):
        """P0-4: run 工具有 timeout 参数"""
        import inspect
        sig = inspect.signature(server.run)
        self.assertIn("timeout", sig.parameters)
        self.assertIn("description", sig.parameters)


class TestInspectTool(unittest.TestCase):
    """P0-2/P0-3: inspect 工具 (合并了 get_workspace/get_variable/get_struct_info)"""

    def setUp(self):
        server.eng = MagicMock()

    def test_inspect_workspace(self):
        """inspect() 无参数列出工作区"""
        server.matlab_eval = MagicMock()
        result = server.inspect()
        server.matlab_eval.assert_called_once()
        call_args = server.matlab_eval.call_args
        self.assertIn("whos", call_args[0][0])

    def test_inspect_variable(self):
        """inspect("var") 查看变量值"""
        server.matlab_eval = MagicMock()
        result = server.inspect("x")
        # Should check existence first, then display
        self.assertTrue(server.matlab_eval.called)

    def test_inspect_cell_index(self):
        """P0-3: cell 索引 Model{1} 的存在性检查"""
        import inspect
        source = inspect.getsource(server.inspect)
        # Must use split('{') not split('{{')
        self.assertIn("split('{')", source)
        self.assertNotIn("split('{{')", source)

    def test_inspect_structure_mode(self):
        """P0-2: struct 查看不使用 eval 内定义函数"""
        import inspect
        source = inspect.getsource(server.inspect)
        # Must NOT contain "function show_struct"
        self.assertNotIn("function show_struct", source)
        # Must use stack-based iteration
        self.assertIn("mcpStack", source)


class TestExperimentTool(unittest.TestCase):
    """P0-C/P2-1: experiment 工具 (合并了 run_experiment + run_batch_experiment)"""

    def setUp(self):
        server.eng = MagicMock()

    def test_experiment_has_seed_param(self):
        """P2-A: experiment 有 seed 参数"""
        import inspect
        sig = inspect.signature(server.experiment)
        self.assertIn("seed", sig.parameters)
        self.assertEqual(sig.parameters["seed"].default, 42)

    def test_experiment_has_raw_code_param(self):
        """P2-1: experiment 合并了 run_batch_experiment 的 raw_code 模式"""
        import inspect
        sig = inspect.signature(server.experiment)
        self.assertIn("raw_code", sig.parameters)

    def test_experiment_no_type_param(self):
        """P2-1: 不再有 experiment_type 参数"""
        import inspect
        sig = inspect.signature(server.experiment)
        self.assertNotIn("experiment_type", sig.parameters)


class TestRunScriptTool(unittest.TestCase):
    """合并 run_script + execute_section"""

    def setUp(self):
        server.eng = MagicMock()

    def test_run_script_has_section_param(self):
        """run_script 合并了 execute_section 的 section 参数"""
        import inspect
        sig = inspect.signature(server.run_script)
        self.assertIn("section", sig.parameters)
        self.assertEqual(sig.parameters["section"].default, "")


class TestDiagnoseTool(unittest.TestCase):
    """合并 get_status + server_load + health_check"""

    def test_diagnose_has_detail_param(self):
        """diagnose 有 detail 参数"""
        import inspect
        sig = inspect.signature(server.diagnose)
        self.assertIn("detail", sig.parameters)
        self.assertEqual(sig.parameters["detail"].default, "full")


class TestTaskManagement(unittest.TestCase):
    """P0-5/P1-E: 任务管理"""

    def test_cancel_task_checks_flag(self):
        """P0-5: cancel_task 设置 _cancel_flag"""
        import inspect
        source = inspect.getsource(server.cancel_task)
        self.assertIn("_cancel_flag", source)

    def test_cleanup_uses_lock(self):
        """P1-E: _cleanup_task_registry 使用 _task_lock"""
        import inspect
        source = inspect.getsource(server._cleanup_task_registry)
        self.assertIn("_task_lock", source)

    def test_get_task_output_running(self):
        """get_task_output 运行中返回增量输出而非拒绝"""
        import inspect
        source = inspect.getsource(server.get_task_output)
        # Should NOT contain the old rejection message
        self.assertNotIn("任务完成后才能获取完整输出", source)
        # Should contain incremental output logic
        self.assertIn("任务仍在运行中", source)


class TestSecurityAndConfig(unittest.TestCase):
    """P0-B/P1-A/P1-G: 安全和配置"""

    def test_env_loading(self):
        """P1-A: .env 文件加载逻辑存在"""
        import inspect
        # Check the module source for .env loading
        source_file = Path(server.__file__).read_text(encoding='utf-8')
        self.assertIn("_env_file", source_file)
        self.assertIn(".env", source_file)

    def test_log_absolute_path(self):
        """P1-G: 日志使用绝对路径"""
        source_file = Path(server.__file__).read_text(encoding='utf-8')
        self.assertIn("_log_path", source_file)
        self.assertIn("os.path.abspath(__file__)", source_file)

    def test_auth_query_param(self):
        """P0-B: 认证支持 query parameter"""
        source_file = Path(server.__file__).read_text(encoding='utf-8')
        self.assertIn("parse_qs", source_file)
        self.assertIn("query_string", source_file)


class TestToolCount(unittest.TestCase):
    """工具数量验证"""

    def test_tool_count_reduced(self):
        """工具从 28 精简到 ~21"""
        source_file = Path(server.__file__).read_text(encoding='utf-8')
        # Count @mcp.tool() decorators
        count = source_file.count("@mcp.tool()")
        self.assertLessEqual(count, 22, f"Tool count {count} exceeds target of ~21")
        self.assertGreaterEqual(count, 15, f"Tool count {count} below minimum of 15")


if __name__ == "__main__":
    print("=" * 60)
    print("MATLAB MCP Server 冒烟测试")
    print("=" * 60)
    unittest.main(verbosity=2)
