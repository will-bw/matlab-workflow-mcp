"""
MATLAB MCP Server v3.0 冒烟测试
===============================
基于 matlab -batch 子进程池架构，无 MATLAB Engine API 依赖。
覆盖计划批次 A（安全/认证/路径沙箱）与批次 B（调度器并发正确性）
以及批次 C 的配置/工具清单。

运行: python test_smoke.py
说明: 本文件 mock FastMCP（@mcp.tool() no-op），无需 mcp 依赖与真实 MATLAB。
"""

import io
import os
import sys
import time
import asyncio
import tempfile
import unittest
import threading
from unittest.mock import MagicMock, patch
from pathlib import Path

# ---------- 导入前准备 ----------
# 1) 日志落地到临时目录，避免污染项目目录 / git status
_TMP_LOG = tempfile.mkdtemp(prefix="mcp_smoke_log_")
os.environ["LOG_DIR"] = _TMP_LOG

# 2) 关闭认证干扰（认证中间件单独测，不依赖全局 token）
os.environ["MCP_TOKEN"] = ""

# 3) mock FastMCP —— v3.0 不再 import matlab.engine，仅需 FastMCP
mock_fastmcp_module = MagicMock()
sys.modules['mcp'] = MagicMock()
sys.modules['mcp.server'] = MagicMock()
mock_fastmcp_module.tool = MagicMock()  # 占位，下面用真实 no-op 覆盖


def _fake_tool():
    """@mcp.tool() 的 no-op 装饰器：保留原函数便于做签名断言。"""
    def decorator(func):
        return func
    return decorator


mock_fastmcp_instance = MagicMock()
mock_fastmcp_instance.tool = _fake_tool
mock_fastmcp_module.FastMCP = MagicMock(return_value=mock_fastmcp_instance)
sys.modules['mcp.server.fastmcp'] = mock_fastmcp_module

# 4) 导入被测服务
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matlab_mcp_server as server


# ============ 被测侧的认证中间件（镜像实现，供功能单测） ============
# 说明: BearerTokenMiddleware 定义于 server 的 __main__ 块内，无法直接 import。
# 此处以其完全一致的逻辑重建用于功能验证；同时以静态断言保证真实实现维持同等安全属性。
# starlette 为部署期依赖，本测试环境未必安装，故以其等价 AST 存根 _FakeJSONResponse 替代。
class _FakeJSONResponse:
    """模拟 starlette JSONResponse 的 ASGI 契约（仅用于拒绝分支）。"""

    def __init__(self, content, status_code=200):
        self.status_code = status_code
        self._content = content

    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start",
                    "status": self.status_code, "headers": []})
        await send({"type": "http.response.body",
                    "body": b"{}", "more_body": False})


class _BearerMW:
    def __init__(self, app, token):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path == "/health":
                await self.app(scope, receive, send)
                return
            authenticated = False
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"")
            if auth.startswith(b"Bearer "):
                supplied = auth[7:].decode()
                authenticated = __import__("hmac").compare_digest(supplied, self.token)
            if not authenticated:
                resp = _FakeJSONResponse({"error": "Unauthorized"}, status_code=401)
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _mk_scope(path, auth_header=None):
    headers = []
    if auth_header is not None:
        headers.append((b"authorization", auth_header.encode()))
    return {"type": "http", "path": path, "headers": headers}


async def _drive(mw, scope):
    """驱动中间件：pass 通过则 app_reached=True；否则捕获 401 状态码。"""
    out = {"reached": False, "status": None}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send_msg(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]

    async def app(scope_, recv, send):
        out["reached"] = True
        await send_msg({"type": "http.response.start", "status": 200, "headers": []})
        await send_msg({"type": "http.response.body", "body": b"", "more_body": False})

    mw.app = app  # 把探针 app 注入中间件
    await mw(scope, receive, send_msg)
    return out


# ============ 路径沙箱 A2 ============
class TestPathSandbox(unittest.TestCase):
    """_resolve_workspace_path —— 拦截路径逃逸（../ 与跨盘符）"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mcp_ws_")

    def test_legal_relative_path(self):
        self._set_ws(self.tmp)
        p = server._resolve_workspace_path("a/b.m")
        self.assertEqual(os.path.realpath(p), os.path.join(os.path.realpath(self.tmp), "a", "b.m"))

    def test_legal_absolute_path(self):
        sub = os.path.join(self.tmp, "sub")
        os.makedirs(sub)
        self._set_ws(self.tmp)
        p = server._resolve_workspace_path(sub)
        self.assertEqual(os.path.realpath(p), os.path.realpath(sub))

    def test_dotdot_escape_rejected(self):
        self._set_ws(self.tmp)
        with self.assertRaises(PermissionError):
            server._resolve_workspace_path("../outside.m")

    def test_absolute_outside_rejected(self):
        outside = tempfile.mkdtemp(prefix="mcp_out_")
        self._set_ws(self.tmp)
        with self.assertRaises(PermissionError):
            server._resolve_workspace_path(os.path.join(outside, "x.m"))

    def test_cross_drive_rejected(self):
        # 模拟 os.path.isabs(True) 但 commonpath 抛 ValueError（不同盘符）
        self._set_ws(self.tmp)
        fake = os.path.join(self.tmp, "ok")  # 合法，先用于对照
        real_commonpath = os.path.commonpath
        with patch.object(os.path, "commonpath", side_effect=ValueError("different drive")):
            with self.assertRaises(PermissionError):
                server._resolve_workspace_path(self.tmp)
        # 还原后合法路径仍可用
        self.assertEqual(server._resolve_workspace_path(fake), os.path.realpath(fake))

    def _set_ws(self, path):
        server.MATLAB_WORKING_DIR = path


# ============ 认证中间件 A3 ============
class TestAuthMiddleware(unittest.TestCase):
    """Bearer header 认证：正确/错误/缺失、/health 放行、query 不再生效"""

    def setUp(self):
        self.mw = _BearerMW(app=None, token="secret-token")

    def test_correct_token_passes(self):
        out = asyncio.run(_drive(self.mw, _mk_scope("/mcp", auth_header="Bearer secret-token")))
        self.assertTrue(out["reached"])

    def test_wrong_token_rejected(self):
        out = asyncio.run(_drive(self.mw, _mk_scope("/mcp", auth_header="Bearer wrong")))
        self.assertFalse(out["reached"])
        self.assertEqual(out["status"], 401)

    def test_missing_header_rejected(self):
        out = asyncio.run(_drive(self.mw, _mk_scope("/mcp", auth_header=None)))
        self.assertFalse(out["reached"])
        self.assertEqual(out["status"], 401)

    def test_non_bearer_header_rejected(self):
        out = asyncio.run(_drive(self.mw, _mk_scope("/mcp", auth_header="Basic abc123")))
        self.assertFalse(out["reached"])
        self.assertEqual(out["status"], 401)

    def test_health_whitelisted(self):
        out = asyncio.run(_drive(self.mw, _mk_scope("/health", auth_header=None)))
        self.assertTrue(out["reached"])

    def test_server_source_security_props(self):
        """真实实现必须使用 compare_digest + Bearer 前缀 + /health 白名单，且移除 query 认证"""
        src = Path(server.__file__).read_text(encoding="utf-8")
        self.assertIn("compare_digest", src)
        self.assertIn("b\"Bearer \"", src)
        self.assertIn('path == "/health"', src)
        # 禁 query string 认证
        self.assertNotIn("parse_qs", src)
        self.assertNotIn("query_string", src)


# ============ 调度器并发正确性 B3 ============
class TestScheduler(unittest.TestCase):
    """队列满拒绝、前台强制、_try_dequeue 资源门控、历史 50 上限、并发快照"""

    def setUp(self):
        server.MAX_CONCURRENT_TASKS = 2
        server.MAX_QUEUE_SIZE = 3
        # 隔离调度器，避免与模块级 daemon 线程互相干扰
        self.sched = server.TaskScheduler()
        # 默认不真正启动子进程
        self.sched._launch = MagicMock(side_effect=lambda t: None)

    def tearDown(self):
        self.sched._reader_pool.shutdown(wait=False, cancel_futures=True)

    def _task(self, code="disp(1)", priority=1):
        return server.ManagedTask(code=code, priority=priority)

    def test_queue_full_rejected(self):
        # 占满并发槽位，迫使后续全部入队；再提交超过 MAX_QUEUE_SIZE 应拒绝
        for i in range(server.MAX_CONCURRENT_TASKS):
            t = self._task()
            self.sched.active[t.task_id] = t
        for _ in range(server.MAX_QUEUE_SIZE):
            accepted, _ = self.sched.submit(self._task())
            self.assertTrue(accepted)
        accepted, msg = self.sched.submit(self._task())
        self.assertFalse(accepted)
        self.assertIn("队列已满", msg)

    def test_foreground_force_start_despite_resources(self):
        with patch.object(server, "_resources_ok", return_value=(False, ["CPU 95%"])):
            t = self._task(priority=0)
            accepted, msg = self.sched.submit(t)
        self.assertTrue(accepted)
        self.assertIn(t.task_id, self.sched.active)
        self.sched._launch.assert_called_with(t)
        self.assertEqual(t.status, "queued")  # Popen 被 mock，未真正 running

    def test_background_queued_when_resources_low(self):
        with patch.object(server, "_resources_ok", return_value=(False, ["CPU 95%"])):
            t = self._task(priority=1)
            accepted, msg = self.sched.submit(t)
        self.assertTrue(accepted)
        self.assertIn(t, list(self.sched.queue))
        self.assertNotIn(t.task_id, self.sched.active)

    def test_try_dequeue_resource_gated(self):
        t = self._task()
        self.sched.queue.append(t)
        with patch.object(server, "_resources_ok", return_value=(False, [])):
            self.sched._try_dequeue()
        self.assertIn(t, list(self.sched.queue))  # 资源不足不启动
        with patch.object(server, "_resources_ok", return_value=(True, [])):
            self.sched._try_dequeue()
        self.assertNotIn(t, list(self.sched.queue))  # 资源充足被取走
        self.assertEqual(self.sched._launch.call_count, 1)

    def test_history_capped_at_50(self):
        for i in range(55):
            t = server.ManagedTask(code="disp(1)")
            t.mark_done("completed")
            self.sched._move_to_history(t)
        self.assertLessEqual(len(self.sched.history), 50)

    def test_concurrent_snapshot_no_runtime_error(self):
        """两线程并发：A 反复列快照，B 反复增删 active——不得抛 RuntimeError"""
        stop = threading.Event()
        errors = []

        def mutator():
            while not stop.is_set():
                t = self._task()
                with self.sched._lock:
                    self.sched.active[t.task_id] = t
                    self.sched.active.pop(t.task_id, None)

        def reader():
            while not stop.is_set():
                try:
                    server.list_tasks()
                except Exception as e:  # noqa
                    errors.append(e)

        threads = [threading.Thread(target=mutator), threading.Thread(target=reader)]
        for th in threads:
            th.start()
        time.sleep(0.4)
        stop.set()
        for th in threads:
            th.join(timeout=2)
        self.assertEqual(errors, [])

    def test_mark_done_idempotent(self):
        """终态只写一次：重复 mark_done 不覆盖早期状态"""
        t = self._task()
        t.mark_done("completed")
        t.end_time_before = t.end_time
        t.mark_done("cancelled")
        self.assertEqual(t.status, "completed")
        self.assertEqual(t.end_time, t.end_time_before)


# ============ 超时 / 取消 分支 B5/B3 ============
class TestTimeoutCancel(unittest.TestCase):
    """_join_task_sync 超时对齐 + cancel 分支"""

    def setUp(self):
        self.sched = server.TaskScheduler()
        self.sched._launch = MagicMock(side_effect=lambda t: None)
        self._orig_scheduler = server.scheduler
        server.scheduler = self.sched

    def tearDown(self):
        server.scheduler = self._orig_scheduler
        self.sched._reader_pool.shutdown(wait=False, cancel_futures=True)

    def test_join_completed_returns_true(self):
        task = server.ManagedTask(code="disp(1)")
        task.mark_done("completed")
        self.assertTrue(server._join_task_sync(task, grace=0))

    def test_join_timeout_status_returns_false(self):
        task = server.ManagedTask(code="disp(1)")
        task.mark_done("timeout")
        self.assertFalse(server._join_task_sync(task, grace=0))

    def test_join_wait_timeout_cancels(self):
        task = server.ManagedTask(code="disp(1)")
        # 人为让 wait 立即返回 False（模拟实际任务超时）
        task._done_event.wait = MagicMock(return_value=False)
        with patch.object(self.sched, "cancel", return_value=True) as cancel:
            result = server._join_task_sync(task, grace=60)
        self.assertFalse(result)
        cancel.assert_called_once_with(task.task_id, reason="timeout")

    def test_cancel_queued_task(self):
        task = server.ManagedTask(code="disp(1)")  # use Mock for timeout check
        self.sched.queue.append(task)
        self.assertTrue(self.sched.cancel(task.task_id))
        self.assertEqual(task.status, "cancelled")
        self.assertNotIn(task, list(self.sched.queue))
        self.assertIn(task.task_id, self.sched.history)

    def test_cancel_missing_returns_false(self):
        self.assertFalse(self.sched.cancel("T9999"))


# ============ 文件工具边界 A2/C ============
class TestFileToolBoundaries(unittest.TestCase):
    """upload_file 大小上限、路径越界拒绝"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mcp_ws_")
        server.MATLAB_WORKING_DIR = self.tmp
        server.MAX_TRANSFER_BYTES = 100  # 缩小便于测试

    def test_upload_over_limit_rejected(self):
        import base64
        data = base64.b64encode(b"x" * 300).decode()
        result = server.upload_file("big.bin", data)
        self.assertIn("FILE_TOO_LARGE", result)

    def test_upload_escape_rejected(self):
        import base64
        data = base64.b64encode(b"ok").decode()
        result = server.upload_file("../evil.m", data)
        self.assertIn("PATH_TRANSLATION", result)

    def test_run_script_escape_rejected(self):
        result = server.run_script("../../../../etc/hostname")
        self.assertIn("PATH_TRANSLATION", result)


# ============ 工具清单 / 配置 C ============
class TestToolsAndConfig(unittest.TestCase):
    """工具清单、配置键、认证策略静态断言"""

    EXPECTED = [
        "run", "run_script", "submit_task", "get_task_status", "get_task_output",
        "cancel_task", "list_tasks", "get_history", "experiment", "inspect",
        "lint_code", "list_files", "transfer_file", "upload_file",
        "save_figure", "diagnose", "sync_status",
    ]

    def test_tool_count_and_names(self):
        src = Path(server.__file__).read_text(encoding="utf-8")
        # 工具由 @mcp.tool() 修饰；定义处应存在对应函数
        for name in self.EXPECTED:
            self.assertTrue(hasattr(server, name), f"缺少工具: {name}")
        count = src.count("@mcp.tool()")
        self.assertEqual(count, 17)

    def test_no_legacy_tools(self):
        src = Path(server.__file__).read_text(encoding="utf-8")
        for legacy in ["set_variable", "get_figure_info", "reset_session",
                       "change_directory", "force_restart_engine", "execute_code"]:
            self.assertNotIn(legacy, src, f"不应存在旧工具 {legacy}")

    def test_config_keys_aligned(self):
        src = Path(server.__file__).read_text(encoding="utf-8")
        self.assertIn("MAX_CONCURRENT_TASKS", src)
        self.assertIn("MAX_QUEUE_SIZE", src)
        # MCP_TOKEN 空值时应有醒目 warning，且不阻断
        self.assertIn("认证未启用", src)
        src_config = Path(server.__file__).parent.joinpath("config.py").read_text(encoding="utf-8")
        # config.py 排除无效键 MAX_RUNNING_TASKS
        self.assertNotIn("MAX_RUNNING_TASKS", src_config)

    def test_env_template_has_no_secret(self):
        env_example = Path(server.__file__).parent.joinpath(".env.example")
        src = env_example.read_text(encoding="utf-8")
        self.assertIn("MCP_TOKEN=", src)
        self.assertIn("MCP_PORT", src)
        # 模板中敏感键的值必须留空（占位，禁止写入真实凭证）
        for key in ["MCP_TOKEN", "TAILSCALE_IP", "PYTHON_PATH"]:
            vals = [line.split("=", 1)[1].strip() for line in src.splitlines()
                    if line.startswith(key + "=")]
            self.assertTrue(vals, f"模板缺少键 {key}")
            self.assertEqual(vals[0], "", f"模板中的 {key} 不应写真实值")

    def test_config_no_legacy_max_running_key(self):
        cfg = Path(server.__file__).parent.joinpath("config.py").read_text(encoding="utf-8")
        self.assertNotIn("MAX_RUNNING_TASKS", cfg)
        self.assertNotIn("bencmark_copy", cfg)


if __name__ == "__main__":
    print("=" * 60)
    print("MATLAB MCP Server v3.0 冒烟测试（子进程池架构）")
    print("=" * 60)
    unittest.main(verbosity=2)