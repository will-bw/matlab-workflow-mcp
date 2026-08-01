"""
MATLAB MCP Server - 远程 MATLAB 执行服务
==========================================
基于 Python MCP SDK (FastMCP) + MATLAB Engine API for Python
为 Paper2 (UAV 动态 4D 路径规划) 项目定制的远程实验执行服务。

传输协议:
  - Streamable HTTP (默认, MCP 规范 2025-03-26): 单端点 /mcp，支持断线重连、动态流式升级
  - SSE (向后兼容): 双端点 /sse + /messages，旧版客户端使用
  - 客户端配置无需修改，Qoder 会自动探测并使用了 Streamable HTTP

工具选择决策树 (22 个工具):
  用户想做什么 → 选哪个工具:
  - 快速验证/执行代码 (< 10分钟)  → run
  - 中等实验 (10-30分钟)          → run(timeout=1800)
  - 长实验 (> 30分钟)              → submit_task
  - 跑现成 .m 脚本                → run_script
  - 跑脚本中某个段落              → run_script(section="1")
  - 跑论文实验配置                → experiment
  - 查看工作区变量                → inspect()
  - 查看某个变量的值/结构          → inspect("var_name")
  - 设置变量                      → set_variable
  - 诊断问题/查看资源             → diagnose
  - 导出图形                      → save_figure
  - 检查代码质量                  → lint_code
  - 文件传输                      → transfer_file / upload_file
  - 查看执行历史                  → get_history

兼容: MATLAB R2022b + Python 3.9-3.10 + MCP SDK >= 1.10.0
参考: neuromechanist/matlab-mcp-tools, jigarbhoye04/MatlabMCP, matlab/matlab-mcp-server (官方)
"""

import os
import sys
import io
import base64
import time
import asyncio
import logging
import traceback
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import matlab.engine
from mcp.server.fastmcp import FastMCP

# ============ 日志配置（带轮转，防止无限增长） ============
from logging.handlers import RotatingFileHandler

# P1-G 修复: 使用绝对路径，避免写入 NSSM AppDirectory
_log_dir = os.environ.get("LOG_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(_log_dir, exist_ok=True)
_log_path = os.path.join(_log_dir, "matlab_mcp_server.log")

_log_handler = RotatingFileHandler(
    _log_path, maxBytes=10*1024*1024, backupCount=3, encoding="utf-8"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        _log_handler,
    ],
)
logger = logging.getLogger("matlab-mcp")

# ============ 配置 ============
# P1-A 修复: 加载 .env 文件（如果存在）
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_file):
    with open(_env_file, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                _key, _val = _key.strip(), _val.strip()
                if _key and _val and _key not in os.environ:
                    os.environ[_key] = _val

# 优先从 config.py 读取，环境变量可覆盖（优先级: 环境变量 > .env > config.py > 默认值）
try:
    from config import MATLAB_WORKING_DIR as _CFG_DIR, HOST as _CFG_HOST, PORT as _CFG_PORT
    from config import MAX_OUTPUT_LENGTH as _CFG_MAX_OUT
    _cfg_available = True
except ImportError:
    _cfg_available = False

MATLAB_WORKING_DIR = os.environ.get("MATLAB_WORKING_DIR", _CFG_DIR if _cfg_available else r"E:\code\Paper2")
HOST = os.environ.get("MCP_HOST", _CFG_HOST if _cfg_available else "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", str(_CFG_PORT if _cfg_available else 8080)))
MAX_OUTPUT_LENGTH = int(os.environ.get("MAX_OUTPUT_LENGTH", str(_CFG_MAX_OUT if _cfg_available else 50000)))
EXEC_TIMEOUT = int(os.environ.get("EXEC_TIMEOUT", "600"))  # 快速操作超时（秒）
AUTO_CAPTURE_FIGURES = os.environ.get("AUTO_CAPTURE_FIGURES", "1") == "1"  # 自动捕获图形
MCP_TOKEN = os.environ.get("MCP_TOKEN", "")  # Bearer Token 认证（空=不启用）

# ============ 资源监控与任务调度配置 ============
MAX_QUEUE_SIZE = int(os.environ.get("MAX_QUEUE_SIZE", "5"))  # 最大排队任务数
MAX_RUNNING_TASKS = int(os.environ.get("MAX_RUNNING_TASKS", "1"))  # 最大同时运行任务数
CPU_THRESHOLD = float(os.environ.get("CPU_THRESHOLD", "90"))  # CPU 使用率阈值 (%)
MEMORY_THRESHOLD = float(os.environ.get("MEMORY_THRESHOLD", "85"))  # 内存使用率阈值 (%)
DISK_THRESHOLD = float(os.environ.get("DISK_THRESHOLD", "95"))  # 磁盘使用率阈值 (%)
RESOURCE_CHECK_ENABLED = os.environ.get("RESOURCE_CHECK", "1") == "1"  # 是否启用资源预检

# ============ 初始化 MCP Server ============
mcp = FastMCP(
    "matlab-server",
    host=HOST,
    port=PORT,
)

# Bearer Token 认证（设置 MCP_TOKEN 环境变量启用）
# 实现真正的 ASGI 中间件校验，而非仅打日志
if MCP_TOKEN:
    logger.info(f"Bearer Token 认证已启用 (token: {MCP_TOKEN[:4]}...)")
else:
    logger.warning("Bearer Token 认证未启用！任何可达此端口的设备均可执行任意 MATLAB 代码。"
                   "设置 MCP_TOKEN 环境变量启用认证。")

# ============ MATLAB Engine 管理 ============
eng = None
_session_start_time = None
_engine_lock = threading.Lock()  # 线程安全：MATLAB Engine 不支持并发调用
_executor = ThreadPoolExecutor(max_workers=1)  # 单线程池，保证顺序执行


# ============ 资源监控器 ============
# 防止持续提交任务导致服务器资源耗尽而崩溃

def _get_system_resources() -> dict:
    """获取系统资源使用情况（兼容有无 psutil）"""
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(MATLAB_WORKING_DIR[:3] if os.name == 'nt' else '/')
        return {
            "cpu_percent": cpu_percent,
            "memory_percent": mem.percent,
            "memory_available_gb": round(mem.available / (1024**3), 1),
            "memory_total_gb": round(mem.total / (1024**3), 1),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024**3), 1),
            "disk_total_gb": round(disk.total / (1024**3), 1),
            "source": "psutil",
        }
    except ImportError:
        # 无 psutil 时使用 Windows 原生命令
        import subprocess
        result = {"source": "wmic_fallback", "cpu_percent": -1, "memory_percent": -1,
                  "memory_available_gb": -1, "memory_total_gb": -1,
                  "disk_percent": -1, "disk_free_gb": -1, "disk_total_gb": -1}
        try:
            if os.name == 'nt':
                # CPU
                out = subprocess.run(
                    ["wmic", "cpu", "get", "loadpercentage", "/value"],
                    capture_output=True, text=True, timeout=5
                )
                for line in out.stdout.splitlines():
                    if "LoadPercentage" in line:
                        result["cpu_percent"] = float(line.split("=")[1].strip())
                # Memory
                out = subprocess.run(
                    ["wmic", "OS", "get", "FreePhysicalMemory,TotalVisibleMemorySize", "/value"],
                    capture_output=True, text=True, timeout=5
                )
                free_kb, total_kb = 0, 0
                for line in out.stdout.splitlines():
                    if "FreePhysicalMemory" in line:
                        free_kb = float(line.split("=")[1].strip())
                    elif "TotalVisibleMemorySize" in line:
                        total_kb = float(line.split("=")[1].strip())
                if total_kb > 0:
                    result["memory_total_gb"] = round(total_kb / (1024**2), 1)
                    result["memory_available_gb"] = round(free_kb / (1024**2), 1)
                    result["memory_percent"] = round((1 - free_kb / total_kb) * 100, 1)
                # Disk
                out = subprocess.run(
                    ["wmic", "logicaldisk", "where", f"DeviceID='{MATLAB_WORKING_DIR[:2]}'",
                     "get", "FreeSpace,Size", "/value"],
                    capture_output=True, text=True, timeout=5
                )
                free_b, total_b = 0, 0
                for line in out.stdout.splitlines():
                    if "FreeSpace" in line and line.split("=")[1].strip():
                        free_b = float(line.split("=")[1].strip())
                    elif "Size" in line and line.split("=")[1].strip():
                        total_b = float(line.split("=")[1].strip())
                if total_b > 0:
                    result["disk_total_gb"] = round(total_b / (1024**3), 1)
                    result["disk_free_gb"] = round(free_b / (1024**3), 1)
                    result["disk_percent"] = round((1 - free_b / total_b) * 100, 1)
            else:
                # Linux/macOS fallback
                import shutil
                total, used, free = shutil.disk_usage('/')
                result["disk_total_gb"] = round(total / (1024**3), 1)
                result["disk_free_gb"] = round(free / (1024**3), 1)
                result["disk_percent"] = round(used / total * 100, 1)
        except Exception:
            pass
        return result


def check_resource_limits() -> tuple:
    """
    检查系统资源是否超过阈值。
    Returns: (is_ok: bool, warnings: list[str])
    """
    if not RESOURCE_CHECK_ENABLED:
        return True, []

    res = _get_system_resources()
    warnings = []

    if res["cpu_percent"] >= 0 and res["cpu_percent"] > CPU_THRESHOLD:
        warnings.append(f"CPU 使用率 {res['cpu_percent']:.0f}% 超过阈值 {CPU_THRESHOLD:.0f}%")
    if res["memory_percent"] >= 0 and res["memory_percent"] > MEMORY_THRESHOLD:
        warnings.append(f"内存使用率 {res['memory_percent']:.0f}% 超过阈值 {MEMORY_THRESHOLD:.0f}%")
    if res["disk_percent"] >= 0 and res["disk_percent"] > DISK_THRESHOLD:
        warnings.append(f"磁盘使用率 {res['disk_percent']:.0f}% 超过阈值 {DISK_THRESHOLD:.0f}%")

    return len(warnings) == 0, warnings


def check_task_queue_limits() -> tuple:
    """
    检查任务队列是否已满。
    Returns: (is_ok: bool, message: str)
    """
    pending = sum(1 for t in _task_registry.values() if t.status == "pending")
    running = sum(1 for t in _task_registry.values() if t.status == "running")

    if running >= MAX_RUNNING_TASKS:
        return False, (
            f"当前有 {running} 个任务正在运行（上限 {MAX_RUNNING_TASKS}）。"
            f"MATLAB Engine 为单线程，无法并行执行。请等待当前任务完成。"
        )
    if pending >= MAX_QUEUE_SIZE:
        return False, (
            f"队列中已有 {pending} 个等待任务（上限 {MAX_QUEUE_SIZE}）。"
            f"请先等待或取消部分任务 (cancel_task)。"
        )
    return True, ""


# ============ 后台任务管理器 ============
# 解决多小时实验的核心方案：提交后立即返回 task_id，不阻塞 SSE 连接

class LiveOutput(io.StringIO):
    """线程安全的实时输出缓冲区（P1-4: 后台任务运行期间即可读取已有输出）"""
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self.last_write_time = None

    def write(self, s):
        with self._lock:
            self.last_write_time = datetime.now()
            return super().write(s)

    def getvalue_safe(self) -> str:
        with self._lock:
            return self.getvalue()


class BackgroundTask:
    """后台任务状态跟踪"""
    def __init__(self, task_id: str, description: str, code: str):
        self.task_id = task_id
        self.description = description
        self.code = code
        self.status = "pending"  # pending -> running -> completed / failed / cancelled
        self.submit_time = datetime.now()
        self.start_time = None
        self.end_time = None
        self.output = ""
        self.error = ""
        self.progress_log = []  # 进度日志
        self._cancel_flag = False
        # P1-4: 实时输出缓冲区
        self.live_stdout = LiveOutput()
        self.live_stderr = LiveOutput()

    @property
    def elapsed(self) -> str:
        """实际执行耗时（不含排队等待）"""
        if self.start_time is None:
            return "等待中"
        end = self.end_time or datetime.now()
        delta = end - self.start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    @property
    def wait_time(self) -> str:
        """排队等待耗时"""
        if self.start_time is None:
            delta = datetime.now() - self.submit_time
        else:
            delta = self.start_time - self.submit_time
        seconds = int(delta.total_seconds())
        if seconds < 1:
            return "<1s"
        elif seconds < 60:
            return f"{seconds}s"
        else:
            return f"{seconds // 60}m {seconds % 60}s"

    @property
    def last_activity(self) -> str:
        """最后一次有输出的时间"""
        t = self.live_stdout.last_write_time or self.live_stderr.last_write_time
        if t is None:
            return "无"
        delta = datetime.now() - t
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return f"{seconds}s 前"
        elif seconds < 3600:
            return f"{seconds // 60}m 前"
        else:
            return f"{seconds // 3600}h {(seconds % 3600) // 60}m 前"

    def to_summary(self) -> str:
        status_icon = {"pending": "⏳", "running": "🔄", "completed": "✅", "failed": "❌", "cancelled": "⛔"}
        icon = status_icon.get(self.status, "?")
        summary = (f"{icon} [{self.task_id}] {self.description}\n"
                   f"   状态: {self.status} | 耗时: {self.elapsed}")
        if self.status == "running":
            summary += f" | 最后活动: {self.last_activity}"
        return summary


_task_registry: dict = {}  # task_id -> BackgroundTask
_task_counter = 0
_task_lock = threading.Lock()


def _run_background_task(task: BackgroundTask):
    """在后台线程中执行长时间 MATLAB 任务"""
    global eng
    logger.info(f"后台任务启动中: [{task.task_id}] {task.description}")

    # P1-4: 使用 LiveOutput 实现实时输出流
    stdout = task.live_stdout
    stderr = task.live_stderr

    try:
        # 检查是否在启动前已被取消
        if task._cancel_flag:
            task.status = "cancelled"
            task.end_time = datetime.now()
            logger.info(f"后台任务启动前已取消: [{task.task_id}]")
            return

        engine = get_engine()

        # P0-3 修复: 获取引擎锁设置 60s 超时，超时则标记 failed
        BG_LOCK_TIMEOUT = 60
        acquired = _engine_lock.acquire(timeout=BG_LOCK_TIMEOUT)
        if not acquired:
            task.status = "failed"
            task.error = (
                f"引擎被其他任务占用超过 {BG_LOCK_TIMEOUT}s，无法启动。"
                f"请等待当前任务完成后再提交。"
            )
            task.end_time = datetime.now()
            logger.error(f"后台任务启动失败(引擎忙): [{task.task_id}]")
            return

        try:
            # 标记任务真正开始执行（计时起点）
            task.status = "running"
            task.start_time = datetime.now()

            # 在 MATLAB 中设置进度回调（写入日志文件）
            progress_file = os.path.join(MATLAB_WORKING_DIR, f"_task_{task.task_id}_progress.txt")
            engine.eval(
                f"fid = fopen('{progress_file}', 'w'); "
                f"fprintf(fid, 'TASK_START %s\\n', datestr(now)); "
                f"fclose(fid);",
                nargout=0
            )

            # 执行任务代码（无超时限制）
            engine.eval(task.code, nargout=0, stdout=stdout, stderr=stderr)
        finally:
            _engine_lock.release()

        # 执行完成后检查是否在执行期间被标记取消
        if task._cancel_flag:
            task.output = stdout.getvalue_safe()
            task.error = "任务在执行完成后被标记为取消（结果可能不完整）"
            task.status = "cancelled"
            logger.info(f"后台任务完成但已被标记取消: [{task.task_id}]")
        else:
            task.output = stdout.getvalue_safe()
            task.error = stderr.getvalue_safe()
            task.status = "completed"
            logger.info(f"后台任务完成: [{task.task_id}] 耗时 {task.elapsed}")

    except matlab.engine.MatlabExecutionError as e:
        task.error = f"{_matlab_error_msg(e)}\n{stderr.getvalue_safe()}"
        task.output = stdout.getvalue_safe()
        task.status = "cancelled" if task._cancel_flag else "failed"
        logger.error(f"后台任务失败: [{task.task_id}] {_matlab_error_msg(e)}")
    except Exception as e:
        task.error = str(e)
        task.status = "cancelled" if task._cancel_flag else "failed"
        logger.error(f"后台任务异常: [{task.task_id}] {e}")
    finally:
        task.end_time = datetime.now()
        # 清理进度文件
        try:
            progress_file = os.path.join(MATLAB_WORKING_DIR, f"_task_{task.task_id}_progress.txt")
            if os.path.exists(progress_file):
                os.remove(progress_file)
        except Exception:
            pass
        # 定期清理任务注册表，防止内存泄漏
        try:
            _cleanup_task_registry()
        except Exception:
            pass


def get_engine():
    """获取或创建 MATLAB Engine 实例（懒加载 + 持久会话 + 线程安全）"""
    global eng, _session_start_time
    with _engine_lock:
        if eng is None:
            logger.info("正在启动 MATLAB Engine...")
            eng = matlab.engine.start_matlab()
            eng.cd(MATLAB_WORKING_DIR, nargout=0)
            # 添加项目必要路径
            eng.eval("addpath(fullfile(pwd, 'aux_files'));", nargout=0)
            eng.eval("addpath(fullfile(pwd, 'methods'));", nargout=0)
            eng.eval("addpath(fullfile(pwd, 'utils'));", nargout=0)
            _session_start_time = datetime.now()
            logger.info(f"MATLAB Engine 已启动，工作目录: {MATLAB_WORKING_DIR}")
    return eng


def matlab_eval(code, nargout=0, stdout=None, stderr=None):
    """
    线程安全的 MATLAB eval 入口。
    所有前台工具的 engine.eval 调用必须通过此函数，
    以防止与后台任务的并发调用冲突（MATLAB Engine 不支持并发）。

    P0-2 修复: 带超时获取锁，引擎被后台任务占用时抛出 EngineBusyError，
    而非无限阻塞导致 MCP 传输层超时崩溃。
    """
    engine = get_engine()
    acquired = _engine_lock.acquire(timeout=FG_LOCK_TIMEOUT)
    if not acquired:
        raise EngineBusyError(
            f"MATLAB 引擎正被后台任务占用（等待 {FG_LOCK_TIMEOUT}s 超时）。"
            f"请使用 get_task_status() 监控后台任务，或等待其完成后再执行前台命令。"
        )
    try:
        return engine.eval(code, nargout=nargout, stdout=stdout, stderr=stderr)
    finally:
        _engine_lock.release()


def run_matlab_sync(func, timeout: int = None):
    """
    在单线程池中执行 MATLAB 调用，防止阻塞事件循环。
    参考: jigarbhoye04/MatlabMCP 的 asyncio.to_thread 模式。
    """
    if timeout is None:
        timeout = EXEC_TIMEOUT
    future = _executor.submit(func)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        raise TimeoutError(f"MATLAB 执行超时（>{timeout}秒）。对于长时间实验，请使用 submit_task 提交后台任务。")


def truncate_output(text: str) -> str:
    """截断过长输出，避免传输超时"""
    if len(text) > MAX_OUTPUT_LENGTH:
        return text[:MAX_OUTPUT_LENGTH] + f"\n\n... [输出已截断，共 {len(text)} 字符]"
    return text


def format_output(stdout_val: str, stderr_val: str = "") -> str:
    """统一格式化输出"""
    result = ""
    if stdout_val:
        result += f"[输出]\n{stdout_val}"
    if stderr_val:
        result += f"\n[警告/信息]\n{stderr_val}"
    if not result:
        result = "[执行完成，无输出]"
    return truncate_output(result)


# ============ P0 修复: 错误处理辅助 ============

class EngineBusyError(Exception):
    """引擎被后台任务占用时抛出，前台工具应捕获并返回友好提示"""
    pass


def _matlab_error_msg(e) -> str:
    """安全提取 MATLAB 异常信息（兼容不同版本 Engine API）"""
    # MatlabExecutionError 的 args[0] 通常是完整错误文本
    msg = getattr(e, 'message', None) or (e.args[0] if e.args else str(e))
    return str(msg)


def _error_response(error_type: str, message: str, elapsed: float = 0, hint: str = "") -> str:
    """结构化错误返回，客户端可根据 error_type 决定下一步操作"""
    # error_type: TIMEOUT | MATLAB_ERROR | ENGINE_BUSY | ENGINE_CRASH | PYTHON_ERROR
    result = f"[{error_type}] {message}"
    if elapsed > 0:
        result += f"\n耗时: {elapsed:.1f}s"
    if hint:
        result += f"\n建议: {hint}"
    return result


# 前台工具获取引擎锁的默认超时（秒）
FG_LOCK_TIMEOUT = int(os.environ.get("FG_LOCK_TIMEOUT", "15"))

# ============ P2-9: 执行历史审计日志 ============
import collections

_execution_history = collections.deque(maxlen=100)  # 环形缓冲区，最近 100 条
_history_lock = threading.Lock()


def _record_execution(tool: str, code_summary: str, elapsed: float, success: bool, error: str = ""):
    """记录每次执行到历史缓冲区"""
    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tool": tool,
        "code": code_summary[:200],
        "elapsed_s": round(elapsed, 1),
        "success": success,
        "error": error[:100] if error else "",
    }
    with _history_lock:
        _execution_history.append(entry)


# ============ 核心工具 ============

@mcp.tool()
async def run(code: str, timeout: int = 0, description: str = "") -> str:
    """
    在 MATLAB 持久会话中执行代码并等待完成。
    变量会在会话中保持，支持连续交互。执行后自动检测新图形。

    选择指南:
    - 快速验证 (< 10分钟): 直接调用本工具，timeout 留默认
    - 中等实验 (10-30分钟): 设置 timeout=1800
    - 长实验 (> 30分钟): 改用 submit_task 提交后台任务

    Args:
        code: 要执行的 MATLAB 代码（可以是多行）
        timeout: 超时秒数（0=默认600秒，可设更大值如 1800）
        description: 实验描述（可选，用于日志和输出标题）

    Returns:
        MATLAB 输出结果 + 耗时统计 + 自动捕获的图形信息
    """
    engine = get_engine()
    t = timeout if timeout > 0 else EXEC_TIMEOUT
    start_time = datetime.now()

    if description:
        logger.info(f"run: {description}")

    def _exec():
        stdout = io.StringIO()
        stderr = io.StringIO()
        # P0-2 修复: 带超时获取锁，避免无限阻塞导致 MCP 传输层崩溃
        acquired = _engine_lock.acquire(timeout=FG_LOCK_TIMEOUT)
        if not acquired:
            raise EngineBusyError(
                f"MATLAB 引擎正被后台任务占用（等待 {FG_LOCK_TIMEOUT}s 超时）。"
                f"请使用 get_task_status() 监控后台任务，或等待其完成后再执行前台命令。"
            )
        try:
            # 记录执行前的图形列表（MATLAB 变量名不能以下划线开头）
            if AUTO_CAPTURE_FIGURES:
                engine.eval("mcpFigsBefore = findall(0, 'Type', 'figure');", nargout=0)
            engine.eval(code, nargout=0, stdout=stdout, stderr=stderr)
            # 检测新生成的图形
            if AUTO_CAPTURE_FIGURES:
                engine.eval(
                    "mcpFigsAfter = findall(0, 'Type', 'figure');\n"
                    "mcpNewFigs = setdiff(mcpFigsAfter, mcpFigsBefore);\n"
                    "if ~isempty(mcpNewFigs)\n"
                    "  fprintf('\\n[自动捕获] 检测到 %d 个新图形 (句柄: %s)\\n', "
                    "length(mcpNewFigs), mat2str(mcpNewFigs'));\n"
                    "end\n"
                    "clear mcpFigsBefore mcpFigsAfter mcpNewFigs;",
                    nargout=0, stdout=stdout, stderr=stderr
                )
        finally:
            _engine_lock.release()
        return stdout.getvalue(), stderr.getvalue()

    try:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(_executor, _exec)
        # P1-6: 心跳保活——每 30s 轮询一次，保持事件循环活跃，防止 SSE 传输层超时断开
        HEARTBEAT_INTERVAL = 30
        while not future.done():
            try:
                out, err = await asyncio.wait_for(asyncio.shield(future), timeout=HEARTBEAT_INTERVAL)
                break  # 执行完成
            except asyncio.TimeoutError:
                elapsed_so_far = (datetime.now() - start_time).total_seconds()
                if elapsed_so_far > t:
                    # 超过用户设置的超时，取消执行
                    future.cancel()
                    return _error_response(
                        "TIMEOUT",
                        f"执行超过 {t} 秒被终止（已耗时 {elapsed_so_far:.0f}s）。",
                        elapsed=elapsed_so_far,
                        hint="对于更长时间的实验，请使用 submit_task 提交后台任务。"
                    )
                # 心跳日志，保持事件循环活跃
                logger.info(f"run heartbeat: {elapsed_so_far:.0f}s elapsed (timeout={t}s)")
        else:
            # future 已完成（循环未 break）
            out, err = future.result()
    except EngineBusyError as e:
        _record_execution("run", code, (datetime.now() - start_time).total_seconds(), False, "ENGINE_BUSY")
        return _error_response("ENGINE_BUSY", str(e))
    except matlab.engine.MatlabExecutionError as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        _record_execution("run", code, elapsed, False, _matlab_error_msg(e))
        return _error_response("MATLAB_ERROR", _matlab_error_msg(e), elapsed=elapsed)
    except Exception as e:
        _record_execution("run", code, (datetime.now() - start_time).total_seconds(), False, str(e))
        return _error_response("PYTHON_ERROR", f"{str(e)}\n{traceback.format_exc()}")

    # 耗时统计
    elapsed = (datetime.now() - start_time).total_seconds()
    _record_execution("run", code, elapsed, True)
    if elapsed > 3600:
        time_str = f"{elapsed/3600:.1f} 小时"
    elif elapsed > 60:
        time_str = f"{elapsed/60:.1f} 分钟"
    else:
        time_str = f"{elapsed:.1f} 秒"

    header = f"[完成] 耗时: {time_str}"
    if description:
        header += f" | {description}"

    return header + "\n" + format_output(out, err)


@mcp.tool()
def run_script(script_path: str, section: str = "") -> str:
    """
    运行 .m 脚本文件，或执行脚本中的指定段落。

    用法:
    - 运行整个脚本: run_script("Main.m")
    - 运行指定段落: run_script("RunExperiments.m", section="1") 或 section="Data Generation"
    - 列出段落: run_script("RunExperiments.m", section="list")

    Args:
        script_path: .m 文件路径（绝对或相对于工作目录）
        section: 段落指定（空=运行全部, 数字=按索引, 文字=按标题匹配, "list"=列出段落）

    Returns:
        脚本执行输出或段落列表
    """
    stdout = io.StringIO()
    stderr = io.StringIO()

    # 解析文件路径
    resolved_path = script_path
    if not os.path.isabs(resolved_path):
        resolved_path = os.path.join(MATLAB_WORKING_DIR, resolved_path)

    # 段落模式
    if section:
        return _run_section(resolved_path, section, stdout, stderr)

    # 整脚本模式
    script_name = os.path.splitext(os.path.basename(script_path))[0]
    try:
        engine = get_engine()
        # P0-2 修复: 带超时获取锁
        acquired = _engine_lock.acquire(timeout=FG_LOCK_TIMEOUT)
        if not acquired:
            return _error_response("ENGINE_BUSY",
                f"MATLAB 引擎正被后台任务占用（等待 {FG_LOCK_TIMEOUT}s 超时）。",
                hint="请等待后台任务完成后再执行前台命令。")
        try:
            original_dir = None
            if os.path.isabs(script_path):
                script_dir = os.path.dirname(script_path)
                original_dir = engine.pwd()
                engine.cd(script_dir, nargout=0, stdout=stdout, stderr=stderr)

            engine.eval(f"run('{script_name}')", nargout=0, stdout=stdout, stderr=stderr)

            if original_dir:
                engine.cd(original_dir, nargout=0)
        finally:
            _engine_lock.release()
    except matlab.engine.MatlabExecutionError as e:
        return f"[MATLAB 错误]\n{_matlab_error_msg(e)}\n\n[stderr]\n{stderr.getvalue()}"
    except Exception as e:
        return f"[Python 错误]\n{str(e)}\n{traceback.format_exc()}"

    return format_output(stdout.getvalue(), stderr.getvalue())


def _run_section(file_path: str, section: str, stdout: io.StringIO, stderr: io.StringIO) -> str:
    """段落执行内部实现"""
    if not os.path.exists(file_path):
        return f"[错误] 文件不存在: {file_path}"

    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    lines = content.split("\n")
    sections = []
    current_title = "(开头)"
    current_lines = []

    for line in lines:
        if line.strip().startswith("%%"):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines)))
            current_title = line.strip().lstrip("%").strip() or f"Section {len(sections)}"
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, "\n".join(current_lines)))

    if not sections:
        return "[错误] 未找到段落（文件为空或无 %% 分隔符）"

    if section.lower() == "list":
        result = f"[文件: {os.path.basename(file_path)}] 共 {len(sections)} 个段落:\n\n"
        for i, (title, code) in enumerate(sections):
            result += f"  [{i}] {title}  ({len(code.split(chr(10)))} 行)\n"
        return result

    if section.lower() == "all":
        try:
            matlab_eval(f"run('{file_path}')", nargout=0, stdout=stdout, stderr=stderr)
        except matlab.engine.MatlabExecutionError as e:
            return f"[MATLAB 错误] {_matlab_error_msg(e)}"
        return format_output(stdout.getvalue(), stderr.getvalue())

    target_idx = -1
    try:
        target_idx = int(section)
    except ValueError:
        for i, (title, _) in enumerate(sections):
            if section.lower() in title.lower():
                target_idx = i
                break
        if target_idx == -1:
            titles = ", ".join([f"[{i}]{t}" for i, (t, _) in enumerate(sections)])
            return f"[错误] 未找到匹配 '{section}' 的段落。可用: {titles}"

    if target_idx < 0 or target_idx >= len(sections):
        return f"[错误] 段落索引 {target_idx} 超出范围 (0-{len(sections)-1})"

    title, code = sections[target_idx]
    try:
        matlab_eval(code, nargout=0, stdout=stdout, stderr=stderr)
    except matlab.engine.MatlabExecutionError as e:
        return f"[MATLAB 错误] 段落 [{target_idx}] '{title}'\n{_matlab_error_msg(e)}"
    except Exception as e:
        return f"[Python 错误] {str(e)}"

    return f"[执行段落 {target_idx}: {title}]\n" + format_output(stdout.getvalue(), stderr.getvalue())


@mcp.tool()
def inspect(var_name: str = "", max_elements: int = 1000, max_depth: int = 2, mode: str = "auto") -> str:
    """
    查看 MATLAB 工作区或指定变量的信息（统一入口）。

    用法:
    - 列出工作区所有变量: inspect()
    - 查看变量值: inspect("result") 或 inspect("Model{1}")
    - 查看 struct 结构: inspect("result", mode="structure")

    Args:
        var_name: 变量名（空=列出工作区，非空=查看该变量）
        max_elements: 最大显示元素数（默认 1000）
        max_depth: struct 递归深度（默认 2，仅 mode=structure 时生效）
        mode: 查看模式 ("auto"=自动判断, "value"=显示值, "structure"=显示结构树)

    Returns:
        工作区变量列表或变量详情
    """
    stdout = io.StringIO()
    stderr = io.StringIO()

    # 无参数: 列出工作区
    if not var_name:
        try:
            matlab_eval("whos", nargout=0, stdout=stdout)
        except Exception as e:
            return f"[错误] {str(e)}"
        output = stdout.getvalue()
        return output if output else "[工作区为空]"

    # 有参数: 查看指定变量
    # 提取基础变量名（处理 Model{1}、result.cost 等表达式）
    base_var = var_name.split('.')[0].split('{')[0]

    try:
        # 检查变量是否存在
        matlab_eval(
            f"if ~exist('{base_var}', 'var'), error('变量不存在: {base_var}'); end",
            nargout=0, stdout=stdout, stderr=stderr
        )
    except matlab.engine.MatlabExecutionError as e:
        return f"[错误] 变量 '{var_name}' 不存在: {_matlab_error_msg(e)}"
    except Exception as e:
        return f"[Python 错误] {str(e)}"

    # 自动判断模式: 如果是 struct/cell 且 mode=auto，显示结构
    if mode == "auto":
        type_stdout = io.StringIO()
        try:
            matlab_eval(f"fprintf('%s', class({var_name}))", nargout=0, stdout=type_stdout)
            var_type = type_stdout.getvalue().strip()
            if var_type in ("struct", "cell"):
                mode = "structure"
            else:
                mode = "value"
        except Exception:
            mode = "value"

    if mode == "structure":
        # 显示结构树
        try:
            matlab_eval(
                f"""
                mcpTarget = {var_name};
                mcpName = '{var_name}';
                mcpMaxDepth = {max_depth};
                mcpStack = {{struct('val', mcpTarget, 'name', mcpName, 'depth', 0)}};
                while ~isempty(mcpStack)
                    mcpItem = mcpStack{{end}};
                    mcpStack(end) = [];
                    s = mcpItem.val;
                    name = mcpItem.name;
                    depth = mcpItem.depth;
                    if depth > mcpMaxDepth, continue; end
                    indent = repmat('  ', 1, depth);
                    if isstruct(s)
                        fns = fieldnames(s);
                        fprintf('%s%s (struct, %d fields)\\n', indent, name, length(fns));
                        for i = length(fns):-1:1
                            val = s.(fns{{i}});
                            if (isstruct(val) || iscell(val)) && depth < mcpMaxDepth
                                mcpStack(end+1) = {{struct('val', val, 'name', fns{{i}}, 'depth', depth+1)}};
                            else
                                fprintf('%s  %s: %s [%s]\\n', indent, fns{{i}}, class(val), num2str(size(val)));
                            end
                        end
                    elseif iscell(s)
                        fprintf('%s%s (cell, %d elements)\\n', indent, name, numel(s));
                        for i = min(3, numel(s)):-1:1
                            if depth < mcpMaxDepth
                                mcpStack(end+1) = {{struct('val', s{{i}}, 'name', sprintf('%s{{%d}}', name, i), 'depth', depth+1)}};
                            end
                        end
                        if numel(s) > 3
                            fprintf('%s  ... (%d more)\\n', indent, numel(s)-3);
                        end
                    else
                        fprintf('%s%s: %s [%s]\\n', indent, name, class(s), num2str(size(s)));
                    end
                end
                clear mcpTarget mcpName mcpMaxDepth mcpStack mcpItem s name depth indent fns i val;
                """,
                nargout=0, stdout=stdout, stderr=stderr
            )
        except matlab.engine.MatlabExecutionError as e:
            return f"[错误] 变量 '{var_name}' 无法解析: {_matlab_error_msg(e)}"
        except Exception as e:
            return f"[Python 错误] {str(e)}"
        return truncate_output(stdout.getvalue()) or "[无输出]"

    else:
        # 显示值
        stdout2 = io.StringIO()
        try:
            matlab_eval(
                f"""
                tmp_var_ = {var_name};
                if numel(tmp_var_) > {max_elements}
                    fprintf('[显示前 {max_elements} 个元素，共 %d 个]\\n', numel(tmp_var_));
                    disp(tmp_var_(1:{max_elements}));
                else
                    disp(tmp_var_);
                end
                clear tmp_var_;
                """,
                nargout=0, stdout=stdout2, stderr=stderr
            )
        except matlab.engine.MatlabExecutionError as e:
            return f"[错误] 变量 '{var_name}' 无法显示: {_matlab_error_msg(e)}"
        except Exception as e:
            return f"[Python 错误] {str(e)}"
        return truncate_output(stdout2.getvalue())


@mcp.tool()
def set_variable(var_name: str, value: str) -> str:
    """
    在 MATLAB 工作区中设置一个变量的值。
    值通过 MATLAB 表达式赋值（如 '1:10', 'rand(3,3)', '"hello"'）。

    Args:
        var_name: 变量名
        value: MATLAB 表达式字符串（如 '[1,2,3]', 'struct("a",1)', 'rand(5)'）

    Returns:
        设置结果确认
    """
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        matlab_eval(f"{var_name} = {value};", nargout=0, stdout=stdout, stderr=stderr)
        # 验证设置成功
        matlab_eval(f"disp({var_name})", nargout=0, stdout=stdout, stderr=stderr)
    except matlab.engine.MatlabExecutionError as e:
        return f"[错误] 设置变量失败: {_matlab_error_msg(e)}"
    except Exception as e:
        return f"[Python 错误] {str(e)}"

    return f"[成功] 变量 '{var_name}' 已设置\n{stdout.getvalue()}"


# ============ 实验运行工具 ============

@mcp.tool()
def experiment(
    algo: str = "HeteroPSO-KR",
    models: str = "1:56",
    n_runs: int = 1,
    output_base: str = "",
    extra_params: str = "",
    seed: int = 42,
    raw_code: str = "",
) -> str:
    """
    运行论文实验（统一入口）。

    两种用法:
    1. 参数化模式: 指定 algo/models/n_runs/seed，调用 mcp_run_experiment.m
    2. 原始代码模式: 传入 raw_code（完整 MATLAB 实验代码），直接执行

    选择指南:
    - 跑论文标准实验 → 用参数化模式
    - 跑自定义/复杂实验组合 → 用 raw_code 模式
    - 实验超过 30 分钟 → 改用 submit_task

    Args:
        algo: 算法名称（默认 'HeteroPSO-KR'）
        models: 模型范围（如 '1:56', '1:10', '[1,5,10]'）
        n_runs: 每个模型重复运行次数
        output_base: 输出目录（默认自动生成带时间戳）
        extra_params: 额外参数（如 'n=10, maxevals=30000, particles=1000'）
        seed: 随机种子（默认 42，确保可复现）
        raw_code: 原始 MATLAB 实验代码（设置后忽略其他参数，直接执行）

    Returns:
        实验运行的输出和状态
    """
    stdout = io.StringIO()
    stderr = io.StringIO()

    # 模式 2: 原始代码模式
    if raw_code:
        logger.info(f"运行原始实验代码")
        try:
            matlab_eval("addpath(fullfile(pwd, 'aux_files'));", nargout=0)
            matlab_eval("addpath(fullfile(pwd, 'methods'));", nargout=0)
            matlab_eval("addpath(fullfile(pwd, 'utils'));", nargout=0)
            matlab_eval(raw_code, nargout=0, stdout=stdout, stderr=stderr)
        except matlab.engine.MatlabExecutionError as e:
            return f"[MATLAB 错误]\n{_matlab_error_msg(e)}\n\n[stderr]\n{stderr.getvalue()}"
        except Exception as e:
            return f"[Python 错误]\n{str(e)}\n{traceback.format_exc()}"
        return format_output(stdout.getvalue(), stderr.getvalue())

    # 模式 1: 参数化模式
    if not output_base:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_base = f"../results_matlab/mcp_run_{timestamp}"

    # 构建 extra_opts struct
    extra_opts_code = "struct()"
    if extra_params:
        pairs = []
        for param in extra_params.split(","):
            param = param.strip()
            if "=" in param:
                k, v = param.split("=", 1)
                pairs.append(f"'{k.strip()}', {v.strip()}")
        if pairs:
            extra_opts_code = f"struct({', '.join(pairs)})"

    run_code = f"""
    mcpOpts = struct();
    mcpOpts.algo = '{algo}';
    mcpOpts.models = {models};
    mcpOpts.n_runs = {n_runs};
    mcpOpts.output_dir = '{output_base}';
    mcpOpts.seed = {seed};
    mcpOpts.extra_opts = {extra_opts_code};
    mcp_run_experiment(mcpOpts);
    clear mcpOpts;
    """
    logger.info(f"运行实验: algo={algo}, models={models}, n_runs={n_runs}, seed={seed}")

    try:
        matlab_eval(run_code, nargout=0, stdout=stdout, stderr=stderr)
    except matlab.engine.MatlabExecutionError as e:
        return f"[MATLAB 错误]\n{_matlab_error_msg(e)}\n\n[stderr]\n{stderr.getvalue()}"
    except Exception as e:
        return f"[Python 错误]\n{str(e)}\n{traceback.format_exc()}"

    return format_output(stdout.getvalue(), stderr.getvalue())


# ============ 后台任务工具（多小时实验） ============

@mcp.tool()
def submit_task(code: str, description: str = "", force: bool = False) -> str:
    """
    提交一个后台 MATLAB 任务，立即返回 task_id，不阻塞连接。
    适合运行需要数小时的实验（如 56 个场景 x 15 次重复）。
    提交前会自动检查服务器负载和队列容量，超载时拒绝提交。

    Args:
        code: 要执行的 MATLAB 代码（可以是完整的实验脚本）
        description: 任务描述（用于日志和状态显示）
        force: 强制提交（跳过资源检查，仅紧急情况使用）

    Returns:
        task_id 和提交确认，或拒绝原因
    """
    global _task_counter

    # === 系统资源检查（在锁外，因为可能耗时） ===
    if not force:
        res_ok, res_warnings = check_resource_limits()
        if not res_ok:
            return (
                f"[任务被拒绝 - 服务器负载过高]\n"
                f"  警告:\n" +
                "".join(f"    ⚠ {w}\n" for w in res_warnings) +
                f"\n建议:\n"
                f"  - 等待服务器负载降低后再提交\n"
                f"  - 使用 server_load() 查看详细资源状态\n"
                f"  - 检查是否有其他程序占用资源\n"
                f"  - 紧急情况可设置 force=True 强制提交"
            )

    # === 队列检查 + 任务注册（原子操作，防止 check-then-act 竞态） ===
    with _task_lock:
        queue_ok, queue_msg = check_task_queue_limits()
        if not queue_ok and not force:
            pending = sum(1 for t in _task_registry.values() if t.status == "pending")
            running = sum(1 for t in _task_registry.values() if t.status == "running")
            return (
                f"[任务被拒绝 - 队列已满]\n"
                f"  原因: {queue_msg}\n"
                f"  当前状态: 运行中 {running} | 排队中 {pending}\n\n"
                f"建议:\n"
                f"  - 等待当前任务完成后再提交\n"
                f"  - 使用 list_tasks() 查看任务状态\n"
                f"  - 使用 cancel_task(task_id) 取消不需要的任务\n"
                f"  - 紧急情况可设置 force=True 强制提交"
            )

        # 通过检查，立即注册任务（在同一把锁内）
        _task_counter += 1
        task_id = f"T{_task_counter:04d}"

        if not description:
            first_line = code.strip().split("\n")[0][:60]
            description = first_line

        task = BackgroundTask(task_id, description, code)
        _task_registry[task_id] = task

    # 在后台线程中启动（不阻塞当前请求）
    thread = threading.Thread(
        target=_run_background_task,
        args=(task,),
        daemon=True,
        name=f"matlab-task-{task_id}"
    )
    thread.start()
    _record_execution("submit_task", code, 0, True)

    # 构建响应（包含当前负载摘要）
    pending_count = sum(1 for t in _task_registry.values() if t.status == "pending")
    running_count = sum(1 for t in _task_registry.values() if t.status == "running")
    force_note = " (强制提交，已跳过资源检查)" if force else ""

    return (
        f"[任务已提交{force_note}]\n"
        f"  Task ID: {task_id}\n"
        f"  描述: {description}\n"
        f"  状态: 已在后台启动\n"
        f"  队列: 运行中 {running_count} | 排队中 {pending_count} | 上限 {MAX_QUEUE_SIZE}\n\n"
        f"提示: 使用以下工具跟踪任务:\n"
        f"  - get_task_status('{task_id}')  查看进度\n"
        f"  - get_task_output('{task_id}')  获取结果\n"
        f"  - list_tasks()  查看所有任务"
    )


@mcp.tool()
def get_task_status(task_id: str = "") -> str:
    """
    查看后台任务的运行状态。
    不需要等待任务完成，可以随时查询。

    Args:
        task_id: 任务 ID（如 'T0001'）。空字符串则显示所有任务。

    Returns:
        任务状态（pending/running/completed/failed）+ 耗时 + 进度
    """
    if not task_id:
        return list_tasks()

    task = _task_registry.get(task_id)
    if not task:
        available = ", ".join(_task_registry.keys()) if _task_registry else "无"
        return f"[错误] 任务 '{task_id}' 不存在。可用任务: {available}"

    result = task.to_summary()

    # 如果正在运行，检查进度文件
    if task.status == "running":
        progress_file = os.path.join(MATLAB_WORKING_DIR, f"_task_{task_id}_progress.txt")
        if os.path.exists(progress_file):
            try:
                with open(progress_file, "r") as f:
                    progress_content = f.read().strip()
                if progress_content:
                    result += f"\n   进度: {progress_content.split(chr(10))[-1]}"
            except Exception:
                pass

    # 如果已完成/失败，显示摘要
    if task.status in ("completed", "failed"):
        if task.output:
            # 显示最后几行输出
            last_lines = task.output.strip().split("\n")[-3:]
            result += f"\n   最后输出: {' | '.join(last_lines)}"
        if task.error and task.status == "failed":
            result += f"\n   错误: {task.error[:200]}"

    # 结构化 JSON 供 AI 客户端可靠解析
    import json as _json
    # P1-4/P1-5: 增加实时输出状态和等待时间
    live_out = task.live_stdout.getvalue_safe() if task.status == "running" else task.output
    json_block = _json.dumps({
        "task_id": task.task_id,
        "status": task.status,
        "description": task.description,
        "elapsed": task.elapsed,
        "wait_time": task.wait_time,
        "has_output": bool(live_out),
        "has_error": bool(task.error),
        "last_activity": task.last_activity if task.status == "running" else None,
    }, ensure_ascii=False)
    result += f"\n---JSON---\n{json_block}"

    return result


@mcp.tool()
def get_task_output(task_id: str, tail_lines: int = 100) -> str:
    """
    获取后台任务的完整输出。
    任务完成后可获取全部 stdout/stderr。

    Args:
        task_id: 任务 ID
        tail_lines: 只显示最后 N 行（默认 100，0=全部）

    Returns:
        任务输出内容
    """
    task = _task_registry.get(task_id)
    if not task:
        return f"[错误] 任务 '{task_id}' 不存在"

    if task.status == "running":
        # P1-4: 运行中从 LiveOutput 实时读取输出
        live_out = task.live_stdout.getvalue_safe()
        result = (
            f"[任务仍在运行中] 耗时: {task.elapsed} | 等待: {task.wait_time} | 最后活动: {task.last_activity}\n"
        )
        if live_out:
            lines = live_out.strip().split("\n")
            tail = "\n".join(lines[-tail_lines:]) if tail_lines > 0 else live_out
            result += f"[实时输出 (最后 {min(tail_lines, len(lines))} 行，共 {len(lines)} 行)]\n{tail}\n"
        else:
            result += "尚无输出。\n"
        result += f"使用 get_task_status('{task_id}') 查看状态。"
        return result

    if task.status == "pending":
        return f"[任务尚未开始] 状态: pending"

    result = f"[任务 {task_id}] 状态: {task.status} | 耗时: {task.elapsed}\n\n"

    output = task.output or ""
    if tail_lines > 0 and len(output.split("\n")) > tail_lines:
        lines = output.split("\n")
        output = f"... (省略前 {len(lines) - tail_lines} 行) ...\n" + "\n".join(lines[-tail_lines:])

    result += f"[输出]\n{output}" if output else "[无输出]"

    if task.error:
        result += f"\n\n[错误/警告]\n{task.error[:5000]}"

    return truncate_output(result)


@mcp.tool()
def cancel_task(task_id: str) -> str:
    """
    取消一个后台任务。
    注意: 如果 MATLAB 代码正在执行中，取消可能不会立即生效
    （需要等待当前 eval 完成）。

    Args:
        task_id: 要取消的任务 ID

    Returns:
        取消结果
    """
    task = _task_registry.get(task_id)
    if not task:
        return f"[错误] 任务 '{task_id}' 不存在"

    if task.status in ("completed", "failed", "cancelled"):
        return f"[提示] 任务 '{task_id}' 已经{task.status}，无需取消"

    task._cancel_flag = True
    task.status = "cancelled"
    task.end_time = datetime.now()
    return f"[已取消] 任务 '{task_id}' 已标记为取消。耗时: {task.elapsed}"


@mcp.tool()
def list_tasks() -> str:
    """
    列出所有后台任务及其状态。

    Returns:
        所有任务的摘要列表
    """
    if not _task_registry:
        return "[无后台任务] 使用 submit_task 提交长时间实验。"

    result = f"[后台任务列表] 共 {len(_task_registry)} 个\n\n"
    for task_id, task in sorted(_task_registry.items()):
        result += task.to_summary() + "\n"

    running = sum(1 for t in _task_registry.values() if t.status == "running")
    if running > 0:
        result += f"\n注意: 有 {running} 个任务正在运行，MATLAB 引擎被占用。"
        result += "\n快速查询工具 (get_workspace 等) 可能需要等待当前任务完成。"

    return result


@mcp.tool()
def get_history(n: int = 20) -> str:
    """
    查看最近的执行历史记录（审计日志）。
    记录所有 run / submit_task 调用的代码摘要、耗时和成功/失败状态。

    Args:
        n: 显示最近 N 条记录（默认 20，最大 100）

    Returns:
        执行历史列表（时间、工具、代码摘要、耗时、状态）
    """
    with _history_lock:
        records = list(_execution_history)

    if not records:
        return "[无执行历史] 尚无 run/submit_task 调用记录。"

    n = min(n, len(records))
    recent = records[-n:]  # 最近 n 条
    recent.reverse()  # 最新的在前

    result = f"[执行历史] 最近 {n} 条（共 {len(records)} 条）\n\n"
    for i, r in enumerate(recent, 1):
        status_icon = "✓" if r["success"] else "✗"
        code_preview = r["code"].replace("\n", " ")[:60]
        elapsed_str = f"{r['elapsed_s']}s" if r["elapsed_s"] > 0 else "-"
        result += f"  {i:2d}. {status_icon} [{r['time']}] {r['tool']} | {elapsed_str}\n"
        result += f"      {code_preview}"
        if r["error"]:
            result += f"\n      错误: {r['error']}"
        result += "\n"

    return result


# ============ 文件与图形工具 ============

@mcp.tool()
def save_figure(
    figure_code: str = "",
    fig_handle: str = "gcf",
    filename: str = "",
    format: str = "png",
    dpi: int = 150,
) -> str:
    """
    将 MATLAB 图形导出为图片文件，并返回 base64 编码。
    可以直接在客户端显示图片。

    Args:
        figure_code: 生成图形的 MATLAB 代码（如 'plot(1:10, rand(1,10))'）。
                     如果为空，则导出当前图形。
        fig_handle: 图形句柄表达式（默认 'gcf'）
        filename: 保存文件名（不含扩展名，默认自动生成）
        format: 图片格式 ('png', 'jpg', 'svg', 'pdf')
        dpi: 分辨率（默认 150）

    Returns:
        base64 编码的图片数据（带前缀标识）
    """
    engine = get_engine()
    stdout = io.StringIO()
    stderr = io.StringIO()

    if not filename:
        filename = f"figure_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    try:
        # 执行绘图代码
        if figure_code:
            matlab_eval(figure_code, nargout=0, stdout=stdout, stderr=stderr)

        # 导出图形
        save_path = os.path.join(MATLAB_WORKING_DIR, "exports")
        matlab_eval(f"if ~exist('{save_path}', 'dir'), mkdir('{save_path}'); end", nargout=0)

        full_path = os.path.join(save_path, f"{filename}.{format}")
        # 使用 MATLAB 的 exportgraphics (R2020a+)
        export_cmd = f"exportgraphics({fig_handle}, '{full_path}', 'Resolution', {dpi})"
        matlab_eval(export_cmd, nargout=0, stdout=stdout, stderr=stderr)

        # 读取文件并编码为 base64
        if os.path.exists(full_path):
            with open(full_path, "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")
            return f"[图片已保存: {full_path}]\n[格式: {format}, DPI: {dpi}]\n[BASE64_START]\n{img_data}\n[BASE64_END]"
        else:
            return f"[错误] 文件未生成: {full_path}\n{stdout.getvalue()}"

    except matlab.engine.MatlabExecutionError as e:
        return f"[MATLAB 错误]\n{_matlab_error_msg(e)}\n\n[stderr]\n{stderr.getvalue()}"
    except Exception as e:
        return f"[Python 错误]\n{str(e)}\n{traceback.format_exc()}"


@mcp.tool()
def transfer_file(file_path: str, encoding: str = "base64") -> str:
    """
    读取 Windows 端的文件并以 base64 编码返回。
    支持传输 .mat, .png, .csv, .txt 等文件到客户端。

    Args:
        file_path: 文件路径（绝对路径或相对于 MATLAB 工作目录）
        encoding: 编码方式（目前仅支持 'base64'）

    Returns:
        文件的 base64 编码内容（带元信息）
    """
    # 处理相对路径（基于 MATLAB 工作目录解析）
    if not os.path.isabs(file_path):
        file_path = os.path.join(MATLAB_WORKING_DIR, file_path)

    if not os.path.exists(file_path):
        return f"[错误] 文件不存在: {file_path}"

    try:
        file_size = os.path.getsize(file_path)
        file_ext = os.path.splitext(file_path)[1].lower()

        # 限制文件大小（50MB）
        if file_size > 50 * 1024 * 1024:
            return f"[错误] 文件过大: {file_size / 1024 / 1024:.1f}MB（限制 50MB）"

        with open(file_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")

        return (
            f"[文件: {os.path.basename(file_path)}]\n"
            f"[路径: {file_path}]\n"
            f"[大小: {file_size} bytes]\n"
            f"[类型: {file_ext}]\n"
            f"[BASE64_START]\n{data}\n[BASE64_END]"
        )
    except Exception as e:
        return f"[错误] 读取文件失败: {str(e)}"


@mcp.tool()
def upload_file(file_path: str, base64_data: str) -> str:
    """
    将 base64 编码的数据写入 Windows 端文件。
    用于从客户端向服务器传输文件。

    Args:
        file_path: 目标文件路径（绝对路径或相对于 MATLAB 工作目录）
        base64_data: base64 编码的文件内容

    Returns:
        写入结果确认
    """
    # 处理相对路径
    if not os.path.isabs(file_path):
        file_path = os.path.join(MATLAB_WORKING_DIR, file_path)

    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        data = base64.b64decode(base64_data)
        with open(file_path, "wb") as f:
            f.write(data)

        return f"[成功] 文件已写入: {file_path} ({len(data)} bytes)"
    except Exception as e:
        return f"[错误] 写入文件失败: {str(e)}"


@mcp.tool()
def list_files(directory: str = ".", pattern: str = "*") -> str:
    """
    列出指定目录中的文件。

    Args:
        directory: 目录路径（默认当前 MATLAB 工作目录）
        pattern: 文件匹配模式（如 '*.mat', '*.m', '*'）

    Returns:
        文件列表（含大小和修改时间）
    """
    try:
        if directory == ".":
            directory = MATLAB_WORKING_DIR
        elif not os.path.isabs(directory):
            directory = os.path.join(MATLAB_WORKING_DIR, directory)

        if not os.path.exists(directory):
            return f"[错误] 目录不存在: {directory}"

        files = []
        for f in sorted(Path(directory).glob(pattern)):
            if f.is_file():
                size = f.stat().st_size
                mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                if size > 1024 * 1024:
                    size_str = f"{size / 1024 / 1024:.1f} MB"
                elif size > 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size} B"
                files.append(f"  {f.name:<40} {size_str:>10}  {mtime}")

        if not files:
            return f"[目录 {directory} 中没有匹配 '{pattern}' 的文件]"

        header = f"[目录: {directory}]\n[匹配: {pattern}] ({len(files)} 个文件)\n"
        return header + "\n".join(files)
    except Exception as e:
        return f"[错误] {str(e)}"


# ============ 代码质量工具 ============

@mcp.tool()
def lint_code(code: str = "", file_path: str = "", severity: str = "all") -> str:
    """
    使用 MATLAB checkcode 进行静态代码分析。
    检查代码风格、潜在错误和最佳实践违规。
    参考: neuromechanist/matlab-mcp-tools 的 matlab_lint 工具。

    Args:
        code: 要检查的 MATLAB 代码（与 file_path 二选一）
        file_path: 要检查的 .m 文件路径（与 code 二选一）
        severity: 过滤级别 ('all', 'warning', 'error')

    Returns:
        代码检查结果（行号 + 消息）
    """
    stdout = io.StringIO()
    stderr = io.StringIO()
    tmp_file = None

    try:
        if file_path:
            # 检查文件
            if not os.path.isabs(file_path):
                file_path = os.path.join(MATLAB_WORKING_DIR, file_path)
            if not os.path.exists(file_path):
                return f"[错误] 文件不存在: {file_path}"
            check_cmd = f"checkcode('{file_path}')"
        elif code:
            # P1-C 修复: 使用 tempfile 防止并发冲突
            import tempfile
            tmp_fd, tmp_file = tempfile.mkstemp(suffix='.m', dir=MATLAB_WORKING_DIR)
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
                f.write(code)
            check_cmd = f"checkcode('{tmp_file}')"
        else:
            return "[错误] 请提供 code 或 file_path 参数"

        # 执行 checkcode 并格式化输出
        matlab_eval(
            f"""
            issues = {check_cmd};
            if isempty(issues)
                fprintf('✓ 未发现问题\\n');
            else
                fprintf('发现 %d 个问题:\\n\\n', length(issues));
                for i = 1:length(issues)
                    fprintf('  L%d: %s\\n', issues(i).line, issues(i).message);
                end
            end
            """,
            nargout=0, stdout=stdout, stderr=stderr
        )

    except matlab.engine.MatlabExecutionError as e:
        return f"[MATLAB 错误] {_matlab_error_msg(e)}"
    except Exception as e:
        return f"[错误] {str(e)}"
    finally:
        # P1-C 修复: 无论是否异常都清理临时文件
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass

    output = stdout.getvalue()
    # 按严重级别过滤
    if severity == "error":
        lines = [l for l in output.split("\n") if "error" in l.lower() or "未发" in l or "发现" in l]
        output = "\n".join(lines) if lines else output
    return truncate_output(output) if output else "[检查完成，无输出]"


# execute_section 已合并入 run_script（通过 section 参数控制）

# get_struct_info 已合并入 inspect 工具（通过 mode="structure" 控制）

@mcp.tool()
def get_figure_info(fig_handle: str = "gcf") -> str:
    """
    获取 MATLAB 图形的元数据（坐标轴、标签、图例、子图信息）。
    参考: neuromechanist/matlab-mcp-tools 的 get_figure_metadata。

    Args:
        fig_handle: 图形句柄表达式（默认 'gcf' 当前图形）

    Returns:
        图形结构信息（标题、轴标签、线图数据等）
    """
    engine = get_engine()
    stdout = io.StringIO()
    stderr = io.StringIO()

    try:
        matlab_eval(
            f"""
            fig = {fig_handle};
            fprintf('图形: %s\\n', get(fig, 'Name'));
            fprintf('大小: %s\\n', mat2str(get(fig, 'Position')));
            axes_list = findobj(fig, 'Type', 'axes');
            fprintf('坐标轴数: %d\\n\\n', length(axes_list));
            for ai = 1:length(axes_list)
                ax = axes_list(ai);
                fprintf('--- Axes %d ---\\n', ai);
                fprintf('  Title: %s\\n', get(get(ax, 'Title'), 'String'));
                fprintf('  XLabel: %s\\n', get(get(ax, 'XLabel'), 'String'));
                fprintf('  YLabel: %s\\n', get(get(ax, 'YLabel'), 'String'));
                lines = findobj(ax, 'Type', 'line');
                fprintf('  线图数: %d\\n', length(lines));
                for li = 1:min(5, length(lines))
                    xd = get(lines(li), 'XData');
                    yd = get(lines(li), 'YData');
                    fprintf('    Line %d: %d points, XRange=[%.2f, %.2f]\\n', ...
                        li, length(xd), min(xd), max(xd));
                end
                leg = legend(ax);
                if ~isempty(leg)
                    fprintf('  Legend: %s\\n', strjoin(get(leg, 'String'), ', '));
                end
            end
            """,
            nargout=0, stdout=stdout, stderr=stderr
        )
    except matlab.engine.MatlabExecutionError as e:
        return f"[错误] 无法获取图形信息: {_matlab_error_msg(e)}"
    except Exception as e:
        return f"[Python 错误] {str(e)}"

    return truncate_output(stdout.getvalue()) or "[无图形]"


# ============ 同步与工作流工具 ============

@mcp.tool()
def sync_status() -> str:
    """
    检查 Syncthing 文件同步状态。
    确认代码是否已同步到 Windows，避免运行旧版本代码。

    Returns:
        Syncthing 连接状态和同步进度
    """
    import urllib.request
    import json

    syncthing_url = os.environ.get("SYNCTHING_URL", "http://127.0.0.1:8384")

    # 解析 URL 中的认证信息 (格式: http://api:KEY@host:port)
    from urllib.parse import urlparse
    parsed = urlparse(syncthing_url)
    api_key = parsed.password if parsed.password else None
    base_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 8384}"

    try:
        # 检查 Syncthing 是否运行
        req = urllib.request.Request(f"{base_url}/rest/system/status")
        req.add_header("Accept", "application/json")
        if api_key:
            req.add_header("X-API-Key", api_key)
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = json.loads(resp.read())

        my_id = status.get("myID", "unknown")[:12]

        # 检查连接
        req2 = urllib.request.Request(f"{base_url}/rest/system/connections")
        req2.add_header("Accept", "application/json")
        if api_key:
            req2.add_header("X-API-Key", api_key)
        with urllib.request.urlopen(req2, timeout=5) as resp2:
            conns = json.loads(resp2.read())

        connections = conns.get("connections", {})
        result = f"[Syncthing 状态]\n  本机 ID: {my_id}...\n"

        if not connections:
            result += "  连接: 无远程设备\n"
        else:
            for dev_id, info in connections.items():
                connected = info.get("connected", False)
                icon = "✓" if connected else "✗"
                result += f"  {icon} 设备 {dev_id[:12]}...: {'connected' if connected else 'disconnected'}\n"

        # 检查文件夹同步状态
        req3 = urllib.request.Request(f"{base_url}/rest/db/status?folder=paper2-code")
        req3.add_header("Accept", "application/json")
        if api_key:
            req3.add_header("X-API-Key", api_key)
        try:
            with urllib.request.urlopen(req3, timeout=5) as resp3:
                folder_status = json.loads(resp3.read())
            in_sync = folder_status.get("inSyncFiles", 0)
            need_sync = folder_status.get("needTotalItems", 0)
            result += f"\n  [代码同步] 已同步: {in_sync} 文件"
            if need_sync > 0:
                result += f", 待同步: {need_sync} 文件 ⚠"
            else:
                result += " ✓ 全部同步"
        except Exception:
            result += "\n  [代码同步] 未配置 paper2-code 文件夹"

        return result

    except Exception as e:
        return (
            f"[Syncthing 不可用] {str(e)}\n"
            f"提示: Syncthing 未运行或地址不对。\n"
            f"当前配置: {syncthing_url}\n"
            f"设置环境变量 SYNCTHING_URL 可修改地址。\n"
            f"如果未使用 Syncthing，代码需通过 Git 或 MCP upload_file 手动同步。"
        )


# run_and_wait 已合并入 run 工具（通过 timeout 参数控制）


# ============ 诊断工具 ============

@mcp.tool()
def diagnose(detail: str = "full") -> str:
    """
    诊断服务器和 MATLAB 会话状态（统一入口）。

    用法:
    - 快速查看资源: diagnose("quick")
    - 全面健康检查: diagnose("full")（默认）

    Args:
        detail: 诊断级别 ("quick"=只看资源和队列, "full"=全链路检查含 MATLAB/Syncthing/Tailscale)

    Returns:
        诊断报告（含是否可接受新任务的判断）
    """
    import json as _json

    res = _get_system_resources()
    res_ok, res_warnings = check_resource_limits()
    queue_ok, queue_msg = check_task_queue_limits()

    pending = sum(1 for t in _task_registry.values() if t.status == "pending")
    running = sum(1 for t in _task_registry.values() if t.status == "running")
    completed = sum(1 for t in _task_registry.values() if t.status == "completed")
    failed = sum(1 for t in _task_registry.values() if t.status == "failed")

    # 资源状态行
    def _bar(percent, threshold):
        if percent < 0:
            return "N/A"
        icon = "⚠" if percent > threshold else "✓"
        filled = int(percent / 5)
        bar = "█" * filled + "░" * (20 - filled)
        return f"{icon} {bar} {percent:.1f}% (阈值 {threshold:.0f}%)"

    lines = ["[服务器诊断]"]

    # 资源部分（quick 和 full 都有）
    lines.extend([
        "",
        f"  CPU:    {_bar(res['cpu_percent'], CPU_THRESHOLD)}",
        f"  内存:   {_bar(res['memory_percent'], MEMORY_THRESHOLD)}",
    ])
    if res['memory_total_gb'] > 0:
        lines.append(f"          可用 {res['memory_available_gb']} GB / 总计 {res['memory_total_gb']} GB")
    lines.append(f"  磁盘:   {_bar(res['disk_percent'], DISK_THRESHOLD)}")
    if res['disk_total_gb'] > 0:
        lines.append(f"          剩余 {res['disk_free_gb']} GB / 总计 {res['disk_total_gb']} GB")

    # 任务队列
    lines.extend([
        "",
        "  [任务队列]",
        f"    运行中: {running}/{MAX_RUNNING_TASKS}  |  排队中: {pending}/{MAX_QUEUE_SIZE}",
        f"    已完成: {completed}  |  已失败: {failed}  |  总计: {len(_task_registry)}",
    ])

    # 服务运行时间
    if _session_start_time:
        delta = datetime.now() - _session_start_time
        hours = delta.total_seconds() / 3600
        lines.append(f"  服务运行: {hours:.1f} 小时")

    all_ok = res_ok and queue_ok

    # full 模式: 额外检查 MATLAB Engine、Syncthing、Tailscale
    if detail == "full":
        lines.append("")
        lines.append("  [组件状态]")

        # MATLAB Engine
        try:
            engine = get_engine()
            acquired = _engine_lock.acquire(timeout=FG_LOCK_TIMEOUT)
            if acquired:
                try:
                    ver = engine.version()
                    cwd = engine.pwd()
                finally:
                    _engine_lock.release()
                lines.append(f"  ✓ MATLAB Engine: {ver}")
                lines.append(f"    工作目录: {cwd}")
            else:
                lines.append(f"  ⚠ MATLAB Engine: 引擎忙（后台任务占用中）")
        except Exception as e:
            lines.append(f"  ✗ MATLAB Engine: {str(e)[:100]}")
            all_ok = False

        # 工作目录
        if os.path.exists(MATLAB_WORKING_DIR):
            m_count = len(list(Path(MATLAB_WORKING_DIR).glob("*.m")))
            lines.append(f"  ✓ 工作目录: {MATLAB_WORKING_DIR} ({m_count} 个 .m 文件)")
        else:
            lines.append(f"  ✗ 工作目录不存在: {MATLAB_WORKING_DIR}")
            all_ok = False

        # Syncthing
        import urllib.request
        syncthing_url = os.environ.get("SYNCTHING_URL", "http://127.0.0.1:8384")
        from urllib.parse import urlparse as _urlparse
        _parsed = _urlparse(syncthing_url)
        _api_key = _parsed.password if _parsed.password else None
        _base_url = f"{_parsed.scheme}://{_parsed.hostname}:{_parsed.port or 8384}"
        try:
            req = urllib.request.Request(f"{_base_url}/rest/system/status")
            req.add_header("Accept", "application/json")
            if _api_key:
                req.add_header("X-API-Key", _api_key)
            with urllib.request.urlopen(req, timeout=3) as resp:
                st = _json.loads(resp.read())
            lines.append(f"  ✓ Syncthing: 运行中 (ID: {st.get('myID', '?')[:8]}...)")
        except Exception:
            lines.append(f"  ○ Syncthing: 不可达 ({syncthing_url})")

        # Tailscale
        import subprocess
        try:
            ts_out = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, timeout=5
            )
            if ts_out.returncode == 0:
                ts_data = _json.loads(ts_out.stdout)
                backend = ts_data.get("BackendState", "Unknown")
                lines.append(f"  ✓ Tailscale: {backend}")
            else:
                lines.append(f"  ✗ Tailscale: 命令失败")
        except FileNotFoundError:
            lines.append(f"  ○ Tailscale: 未安装 (非必须)")
        except Exception as e:
            lines.append(f"  ○ Tailscale: {str(e)[:50]}")

    # 结论
    lines.append("")
    if all_ok:
        lines.append("  [结论] ✓ 服务器状态良好，可以接受新任务")
    else:
        lines.append("  [结论] ⚠ 当前不建议提交新任务:")
        for w in res_warnings:
            lines.append(f"    - {w}")
        if not queue_ok:
            lines.append(f"    - {queue_msg}")

    # 结构化 JSON
    json_block = _json.dumps({
        "cpu_percent": res["cpu_percent"],
        "memory_percent": res["memory_percent"],
        "memory_available_gb": res["memory_available_gb"],
        "disk_percent": res["disk_percent"],
        "disk_free_gb": res["disk_free_gb"],
        "tasks_running": running,
        "tasks_pending": pending,
        "can_accept_task": all_ok,
        "warnings": res_warnings if not res_ok else [],
    }, ensure_ascii=False)
    lines.append(f"\n---JSON---\n{json_block}")

    return "\n".join(lines)


# ============ 会话管理工具 ============

@mcp.tool()
def force_restart_engine() -> str:
    """
    强制重启 MATLAB Engine。
    当引擎卡死（如超时后 MATLAB 仍在跑且占用单线程池）时使用此工具恢复服务。
    注意: 这会丢失当前工作区所有变量。

    Returns:
        重启结果确认
    """
    global eng, _session_start_time
    import subprocess as _sp

    logger.warning("强制重启 MATLAB Engine...")

    # 尝试正常退出
    try:
        if eng is not None:
            eng.quit()
    except Exception:
        pass

    # P1-D 修复: 仅杀 Engine API 启动的 MATLAB 进程（-automation 标志）
    try:
        if os.name == 'nt':
            # 查找带 -automation 标志的 MATLAB 进程
            result = _sp.run(
                ["wmic", "process", "where", "name='MATLAB.exe'",
                 "get", "ProcessId,CommandLine", "/format:csv"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                if "MATLAB.exe" in line and "-automation" in line:
                    parts = line.strip().split(",")
                    if parts and parts[-1].strip().isdigit():
                        _sp.run(["taskkill", "/F", "/PID", parts[-1].strip()],
                                capture_output=True, timeout=5)
        else:
            _sp.run(["pkill", "-9", "-f", "matlab.*-automation"], capture_output=True, timeout=10)
    except Exception:
        pass

    # 重置状态
    eng = None
    _session_start_time = None
    import time as _time
    _time.sleep(2)  # 等待进程完全退出

    # 重新启动
    try:
        get_engine()
        return "[成功] MATLAB Engine 已强制重启。工作区变量已清空。"
    except Exception as e:
        return f"[失败] 重启失败: {str(e)}。请检查 MATLAB 安装是否正常。"


def _cleanup_task_registry():
    """清理已完成/失败/取消的任务，防止内存无限增长"""
    MAX_FINISHED_TASKS = 50  # 最多保留 50 个已完成任务
    MAX_OUTPUT_SIZE = 1024 * 1024  # 单个任务输出上限 1MB

    # P1-E 修复: 加锁防止并发修改字典
    with _task_lock:
        finished = [
            (tid, t) for tid, t in _task_registry.items()
            if t.status in ("completed", "failed", "cancelled")
        ]

        # 截断过大的输出
        for tid, t in finished:
            if len(t.output) > MAX_OUTPUT_SIZE:
                t.output = t.output[:MAX_OUTPUT_SIZE] + f"\n... [output truncated, was {len(t.output)} chars]"

        # 删除最老的已完成任务
        if len(finished) > MAX_FINISHED_TASKS:
            finished.sort(key=lambda x: x[1].end_time or x[1].submit_time)
            for tid, _ in finished[:len(finished) - MAX_FINISHED_TASKS]:
                del _task_registry[tid]
                logger.info(f"清理旧任务记录: {tid}")


# get_status 已合并入 diagnose 工具（通过 detail 参数控制）


@mcp.tool()
def reset_session(clear_all: bool = False) -> str:
    """
    重置 MATLAB 工作区。

    Args:
        clear_all: 是否同时关闭所有图形窗口并清除命令历史（默认 False）

    Returns:
        重置结果确认
    """
    stdout = io.StringIO()

    try:
        if clear_all:
            matlab_eval("clear all; close all; clc;", nargout=0, stdout=stdout)
            msg = "[已重置] 工作区已清空，图形已关闭，命令行已清除"
        else:
            matlab_eval("clear; clc;", nargout=0, stdout=stdout)
            msg = "[已重置] 工作区变量已清空"

        # 重新添加路径
        matlab_eval("addpath(fullfile(pwd, 'aux_files'));", nargout=0)
        matlab_eval("addpath(fullfile(pwd, 'methods'));", nargout=0)
        matlab_eval("addpath(fullfile(pwd, 'utils'));", nargout=0)

        return msg
    except Exception as e:
        return f"[错误] 重置失败: {str(e)}"


@mcp.tool()
def change_directory(path: str) -> str:
    """
    更改 MATLAB 当前工作目录。

    Args:
        path: 目标目录路径

    Returns:
        切换结果确认
    """
    stdout = io.StringIO()
    stderr = io.StringIO()

    try:
        engine = get_engine()
        acquired = _engine_lock.acquire(timeout=FG_LOCK_TIMEOUT)
        if not acquired:
            return _error_response("ENGINE_BUSY",
                f"MATLAB 引擎正被后台任务占用（等待 {FG_LOCK_TIMEOUT}s 超时）。",
                hint="请等待后台任务完成后再执行前台命令。")
        try:
            engine.cd(path, nargout=0, stdout=stdout, stderr=stderr)
            current = engine.pwd()
        finally:
            _engine_lock.release()
        return f"[成功] 工作目录已切换为: {current}"
    except matlab.engine.MatlabExecutionError as e:
        return f"[错误] 无法切换目录: {_matlab_error_msg(e)}"
    except Exception as e:
        return f"[Python 错误] {str(e)}"


# ============ 启动 ============
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="MATLAB MCP Server - 远程 MATLAB 执行服务",
        epilog="配置也可通过环境变量设置: MATLAB_WORKING_DIR, MCP_HOST, MCP_PORT, MAX_OUTPUT_LENGTH, MCP_TOKEN"
    )
    parser.add_argument("--workdir", default=None, help="MATLAB 工作目录 (覆盖环境变量)")
    parser.add_argument("--no-preload", action="store_true", help="不预启动 MATLAB Engine")
    parser.add_argument(
        "--transport", choices=["streamable-http", "sse"], default="streamable-http",
        help="传输协议: streamable-http (默认, MCP 2025-03-26 规范) 或 sse (向后兼容旧客户端)"
    )
    args = parser.parse_args()

    # 应用命令行参数（workdir 可覆盖）
    if args.workdir:
        MATLAB_WORKING_DIR = args.workdir

    # 传输协议也可通过环境变量覆盖
    TRANSPORT = os.environ.get("MCP_TRANSPORT", args.transport)

    # 确定端点路径
    if TRANSPORT == "streamable-http":
        endpoint_path = "/mcp"
    else:
        endpoint_path = "/sse"

    logger.info("=" * 60)
    logger.info("MATLAB MCP Server 启动")
    logger.info(f"  传输协议: {TRANSPORT}")
    logger.info(f"  监听地址: http://{HOST}:{PORT}{endpoint_path}")
    logger.info(f"  健康检查: http://{HOST}:{PORT}/health")
    logger.info(f"  工作目录: {MATLAB_WORKING_DIR}")
    logger.info(f"  最大输出: {MAX_OUTPUT_LENGTH} 字符")
    logger.info(f"  认证: {'Bearer Token 已启用' if MCP_TOKEN else '未启用 (警告: 任何可达设备可执行代码)'}")
    logger.info("=" * 60)

    # 预启动 MATLAB Engine（加快首次响应）
    if not args.no_preload:
        try:
            get_engine()
        except Exception as e:
            logger.error(f"MATLAB Engine 启动失败: {e}")
            logger.error("请确保 MATLAB 已正确安装且 Engine API 已配置")
            logger.error("提示: 使用 --no-preload 跳过预启动，在首次调用时再启动")
            sys.exit(1)

    # ============ 启动服务 ============
    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route, Mount
    from starlette.types import ASGIApp, Receive, Scope, Send

    # P2-8: 健康检查端点（无需认证，供客户端探活）
    async def health_check(request: Request):
        running = sum(1 for t in _task_registry.values() if t.status == "running")
        pending = sum(1 for t in _task_registry.values() if t.status == "pending")
        uptime = (datetime.now() - _session_start_time).total_seconds() if _session_start_time else 0
        return JSONResponse({
            "status": "ok" if eng is not None else "no_engine",
            "engine_busy": _engine_lock.locked(),
            "tasks_running": running,
            "tasks_pending": pending,
            "uptime_seconds": round(uptime),
            "transport": TRANSPORT,
            "version": "2.0",
        })

    # Bearer Token 认证中间件
    class BearerTokenMiddleware:
        """ASGI 中间件：校验 Authorization: Bearer <token> 头或 ?token= query param"""
        def __init__(self, app: ASGIApp, token: str):
            self.app = app
            self.token = token

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if scope["type"] == "http":
                # /health 端点无需认证
                path = scope.get("path", "")
                if path == "/health":
                    await self.app(scope, receive, send)
                    return

                authenticated = False

                # 方式 1: Authorization: Bearer <token> header
                headers = dict(scope.get("headers", []))
                auth_header = headers.get(b"authorization", b"").decode()
                if auth_header.startswith("Bearer ") and auth_header[7:] == self.token:
                    authenticated = True

                # 方式 2: ?token=<token> query parameter
                if not authenticated:
                    from urllib.parse import parse_qs
                    query_string = scope.get("query_string", b"").decode()
                    params = parse_qs(query_string)
                    if params.get("token", [""])[0] == self.token:
                        authenticated = True

                if not authenticated:
                    response = JSONResponse(
                        {"error": "Unauthorized", "message": "Invalid or missing token. Use Authorization: Bearer <token> header or ?token=<token> query param."},
                        status_code=401
                    )
                    await response(scope, receive, send)
                    return
            await self.app(scope, receive, send)

    # 获取 MCP 协议的 ASGI app
    if TRANSPORT == "streamable-http":
        # Streamable HTTP (MCP 规范 2025-03-26，替代已废弃的 SSE)
        # 单端点 /mcp，支持动态连接升级、断线重连、多客户端并发
        try:
            mcp_app = mcp.streamable_http_app()
            logger.info("使用 Streamable HTTP 传输 (MCP 2025-03-26)")
        except AttributeError:
            # SDK 版本过低，回退到 SSE
            logger.warning("MCP SDK 不支持 streamable_http_app()，回退到 SSE 传输")
            logger.warning("请升级: pip install 'mcp[cli]>=1.10.0'")
            mcp_app = mcp.sse_app()
            TRANSPORT = "sse"
    else:
        # SSE (向后兼容旧客户端)
        mcp_app = mcp.sse_app()
        logger.info("使用 SSE 传输 (向后兼容模式)")

    # 包装认证中间件
    if MCP_TOKEN:
        mcp_app = BearerTokenMiddleware(mcp_app, MCP_TOKEN)

    # 组合路由: /health + MCP 协议端点
    app = Starlette(routes=[
        Route("/health", health_check),
        Mount("/", app=mcp_app),
    ])
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
