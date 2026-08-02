"""
MATLAB MCP Server v3.0 - 子进程池架构
========================================
基于 matlab -batch 子进程执行，支持真正并行。
无 MATLAB Engine API 依赖，仅需 matlab 可执行文件在 PATH 中。

架构:
  - 每次执行启动独立 matlab -batch 进程
  - TaskScheduler 智能调度（资源监控 + 并发控制 + 排队）
  - 最多 MAX_CONCURRENT_TASKS 个 MATLAB 进程同时运行
  - 前台 run 同步等待，后台 submit_task 立即返回

传输: Streamable HTTP (MCP 2025-03-26) | SSE (向后兼容)
工具: 17 个 MCP tools
兼容: MATLAB R2021a+ | Python 3.9+ | 无需 Engine API
"""

import os
import sys
import io
import time
import base64
import asyncio
import hmac
import logging
import tempfile
import threading
import subprocess
import collections
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from mcp.server.fastmcp import FastMCP

# ============ 日志配置 ============
from logging.handlers import RotatingFileHandler

# 配置加载须在日志初始化之前，确保 LOG_DIR 等来自 .env 的配置立即生效
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

_log_dir = os.environ.get("LOG_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(_log_dir, exist_ok=True)
_log_path = os.path.join(_log_dir, "matlab_mcp_server.log")

_log_handler = RotatingFileHandler(
    _log_path, maxBytes=10*1024*1024, backupCount=3, encoding="utf-8"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), _log_handler],
)
logger = logging.getLogger("matlab-mcp")

try:
    from config import (
        MATLAB_WORKING_DIR as _CFG_DIR, HOST as _CFG_HOST, PORT as _CFG_PORT,
        MAX_OUTPUT_LENGTH as _CFG_MAX_OUT, MATLAB_EXE as _CFG_MATLAB_EXE,
        MAX_CONCURRENT_TASKS as _CFG_MAX_TASKS, MAX_QUEUE_SIZE as _CFG_MAX_QUEUE,
        TASK_TIMEOUT_DEFAULT as _CFG_TIMEOUT, CPU_THRESHOLD as _CFG_CPU,
        MEMORY_THRESHOLD as _CFG_MEM, DISK_THRESHOLD as _CFG_DISK,
        MCP_TOKEN as _CFG_TOKEN,
    )
    _cfg = True
except ImportError:
    _cfg = False

MATLAB_WORKING_DIR = os.environ.get("MATLAB_WORKING_DIR", _CFG_DIR if _cfg else r"E:\code\Paper2")
HOST = os.environ.get("MCP_HOST", _CFG_HOST if _cfg else "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", str(_CFG_PORT if _cfg else 8080)))
MAX_OUTPUT_LENGTH = int(os.environ.get("MAX_OUTPUT_LENGTH", str(_CFG_MAX_OUT if _cfg else 50000)))
MATLAB_EXE = os.environ.get("MATLAB_EXE", _CFG_MATLAB_EXE if _cfg else "")
MAX_CONCURRENT_TASKS = int(os.environ.get("MAX_CONCURRENT_TASKS", str(_CFG_MAX_TASKS if _cfg else 3)))
MAX_QUEUE_SIZE = int(os.environ.get("MAX_QUEUE_SIZE", str(_CFG_MAX_QUEUE if _cfg else 10)))
TASK_TIMEOUT_DEFAULT = int(os.environ.get("TASK_TIMEOUT_DEFAULT", str(_CFG_TIMEOUT if _cfg else 600)))
CPU_THRESHOLD = float(os.environ.get("CPU_THRESHOLD", str(_CFG_CPU if _cfg else 85)))
MEMORY_THRESHOLD = float(os.environ.get("MEMORY_THRESHOLD", str(_CFG_MEM if _cfg else 80)))
DISK_THRESHOLD = float(os.environ.get("DISK_THRESHOLD", str(_CFG_DISK if _cfg else 95)))
MCP_TOKEN = os.environ.get("MCP_TOKEN", _CFG_TOKEN if _cfg else "")

# ============ MCP Server 初始化 ============
mcp = FastMCP("matlab-server", host=HOST, port=PORT)

if MCP_TOKEN:
    logger.info(f"Bearer Token 认证已启用 (token: {MCP_TOKEN[:4]}...)")
else:
    logger.warning("认证未启用！设置 MCP_TOKEN 环境变量启用。公网/非信任网络下部署存在未授权访问风险，强烈建议启用。")


# ============ 工具函数 ============

def _error_response(error_type: str, message: str, elapsed: float = 0, hint: str = "") -> str:
    """结构化错误返回"""
    result = f"[{error_type}] {message}"
    if elapsed > 0:
        result += f"\n耗时: {elapsed:.1f}s"
    if hint:
        result += f"\n建议: {hint}"
    return result


MAX_TRANSFER_BYTES = 50 * 1024 * 1024


def _resolve_workspace_path(file_path: str) -> str:
    """将用户输入路径解析为工作区内的绝对路径，防止路径沙箱逃逸。

    - 绝对路径：校验其位于 MATLAB_WORKING_DIR 之内；
    - 相对路径：先拼接到工作区再做校验（拦截 ../ 及盘符切换）。

    越界时抛 PermissionError。
    """
    base = os.path.realpath(MATLAB_WORKING_DIR)
    candidate = file_path if os.path.isabs(file_path) else os.path.join(MATLAB_WORKING_DIR, file_path)
    candidate = os.path.realpath(candidate)
    try:
        if os.path.commonpath([base, candidate]) != base:
            raise PermissionError(f"路径越界，拒绝访问工作区外路径: {file_path}")
    except ValueError:
        # 不同盘符（如 C:\ vs E:\）必然越界
        raise PermissionError(f"路径越界，拒绝访问工作区外路径: {file_path}")
    return candidate


def truncate_output(text: str) -> str:
    if len(text) > MAX_OUTPUT_LENGTH:
        return text[:MAX_OUTPUT_LENGTH] + f"\n\n... [输出已截断，共 {len(text)} 字符]"
    return text


def _find_matlab_exe() -> str:
    """定位 MATLAB 可执行文件"""
    global MATLAB_EXE
    if MATLAB_EXE and os.path.isfile(MATLAB_EXE):
        return MATLAB_EXE
    # 尝试 PATH 查找
    import shutil
    found = shutil.which("matlab")
    if found:
        MATLAB_EXE = found
        return found
    # 常见路径猜测
    common_paths = [
        r"C:\Program Files\MATLAB\R2022b\bin\matlab.exe",
        r"C:\Program Files\MATLAB\R2023a\bin\matlab.exe",
        r"C:\Program Files\MATLAB\R2023b\bin\matlab.exe",
        r"C:\Program Files\MATLAB\R2024a\bin\matlab.exe",
        r"C:\Program Files\MATLAB\R2024b\bin\matlab.exe",
    ]
    for p in common_paths:
        if os.path.isfile(p):
            MATLAB_EXE = p
            return p
    raise FileNotFoundError(
        "找不到 MATLAB 可执行文件。请设置 MATLAB_EXE 环境变量或确保 matlab 在 PATH 中。"
    )


def _matlab_string_escape(s: str) -> str:
    """将路径/字符串转为 MATLAB 单引号字符串内的合法字面量。

    - 单引号须翻倍（''）；
    - 反斜杠统一为 /，避免 MATLAB 将其解析为转义序列。
    """
    return s.replace("\\", "/").replace("'", "''")


def _matlab_script_encoding() -> str:
    """返回 MATLAB 脚本文件的写入编码。

    Windows 上使用 utf-8-sig（带 BOM），确保 MATLAB 正确识别 UTF-8，
    而非回退到系统 ANSI 代码页（中文 Windows 为 GBK/CP936）。
    """
    return "utf-8-sig" if os.name == "nt" else "utf-8"


def _build_wrapped_code(code: str) -> str:
    """构建包含 cd + try/catch 的完整 MATLAB 执行代码。"""
    workdir = _matlab_string_escape(MATLAB_WORKING_DIR)
    wrapped = f"cd('{workdir}');\n"
    wrapped += "try\n"
    # 统一换行符，防止 \r\n 输入在 Windows text 模式下产生 \r\r\n
    body = code.replace("\r\n", "\n").replace("\r", "\n").lstrip("\n \t")
    if not body:
        body = "disp('(empty script)')"
    for line in body.split("\n"):
        wrapped += f"    {line}\n"
    wrapped += "catch ME\n"
    wrapped += "    fprintf(2, 'MATLAB_ERROR: %s\\n', ME.message);\n"
    wrapped += "    for k = 1:length(ME.stack)\n"
    wrapped += "        fprintf(2, '  at %s (line %d)\\n', ME.stack(k).name, ME.stack(k).line);\n"
    wrapped += "    end\n"
    wrapped += "    exit(1);\n"
    wrapped += "end\n"
    return wrapped


def _write_temp_script(code: str, task_id: str) -> str:
    """将 MATLAB 代码写入临时 .m 文件，返回文件路径"""
    script_name = f"_mcp_task_{task_id}.m"
    script_path = os.path.join(MATLAB_WORKING_DIR, script_name)
    os.makedirs(MATLAB_WORKING_DIR, exist_ok=True)
    wrapped = _build_wrapped_code(code)
    with open(script_path, "w", encoding=_matlab_script_encoding()) as f:
        f.write(wrapped)
    return script_path


def _cleanup_temp_script(task_id: str):
    """清理临时脚本文件"""
    script_path = os.path.join(MATLAB_WORKING_DIR, f"_mcp_task_{task_id}.m")
    try:
        if os.path.exists(script_path):
            os.remove(script_path)
    except Exception:
        pass


# ============ 资源监控 ============

def _get_system_resources() -> dict:
    """获取系统资源使用情况"""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(MATLAB_WORKING_DIR[:3] if os.name == 'nt' else '/')
        return {
            "cpu_percent": cpu,
            "memory_percent": mem.percent,
            "memory_available_gb": round(mem.available / (1024**3), 1),
            "memory_total_gb": round(mem.total / (1024**3), 1),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024**3), 1),
        }
    except ImportError:
        return {"cpu_percent": -1, "memory_percent": -1, "memory_available_gb": -1,
                "memory_total_gb": -1, "disk_percent": -1, "disk_free_gb": -1}


_res_cache = {"ts": 0.0, "ok": True, "warnings": []}


def _resources_ok() -> tuple:
    """检查资源是否允许启动新任务。Returns: (ok, warnings)

    带 <2s 缓存，避免前台频繁调用时被 psutil 阻塞采样。
    """
    now = time.monotonic()
    if now - _res_cache["ts"] < 2.0:
        return _res_cache["ok"], list(_res_cache["warnings"])
    res = _get_system_resources()
    warnings = []
    if res["cpu_percent"] >= 0 and res["cpu_percent"] > CPU_THRESHOLD:
        warnings.append(f"CPU {res['cpu_percent']:.0f}% > {CPU_THRESHOLD:.0f}%")
    if res["memory_percent"] >= 0 and res["memory_percent"] > MEMORY_THRESHOLD:
        warnings.append(f"内存 {res['memory_percent']:.0f}% > {MEMORY_THRESHOLD:.0f}%")
    if res["disk_percent"] >= 0 and res["disk_percent"] > DISK_THRESHOLD:
        warnings.append(f"磁盘 {res['disk_percent']:.0f}% > {DISK_THRESHOLD:.0f}%")
    ok = len(warnings) == 0
    _res_cache.update(ts=now, ok=ok, warnings=warnings)
    return ok, warnings


# ============ 任务模型 ============

class ManagedTask:
    """任务状态模型"""
    _counter = 0
    _counter_lock = threading.Lock()

    def __init__(self, code: str, description: str = "", timeout: int = 0,
                 priority: int = 1, working_dir: str = ""):
        with ManagedTask._counter_lock:
            ManagedTask._counter += 1
            self.task_id = f"T{ManagedTask._counter:04d}"
        self.code = code
        self.description = description or code.strip().split("\n")[0][:60]
        self.timeout = timeout if timeout > 0 else TASK_TIMEOUT_DEFAULT
        self.priority = priority  # 0=前台(高), 1=后台(低)
        self.working_dir = working_dir or MATLAB_WORKING_DIR
        self.status = "queued"  # queued → running → completed/failed/cancelled/timeout
        self.submit_time = datetime.now()
        self.start_time = None
        self.end_time = None
        self.process = None  # subprocess.Popen
        self.output_lines = []  # 实时输出
        self._output_lock = threading.Lock()
        self._done_event = threading.Event()
        self.exit_code = None

    @property
    def done(self) -> bool:
        return self._done_event.is_set()

    @property
    def elapsed(self) -> str:
        if self.start_time is None:
            return "等待中"
        end = self.end_time or datetime.now()
        delta = end - self.start_time
        h, rem = divmod(int(delta.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h}h {m}m {s}s"
        elif m > 0:
            return f"{m}m {s}s"
        return f"{s}s"

    @property
    def wait_time(self) -> str:
        if self.start_time is None:
            delta = datetime.now() - self.submit_time
        else:
            delta = self.start_time - self.submit_time
        s = int(delta.total_seconds())
        return f"{s}s" if s < 60 else f"{s//60}m {s%60}s"

    def get_output(self, tail: int = 0) -> str:
        with self._output_lock:
            lines = list(self.output_lines)
        if tail > 0 and len(lines) > tail:
            return "\n".join(lines[-tail:])
        return "\n".join(lines)

    def append_output(self, line: str):
        with self._output_lock:
            self.output_lines.append(line)

    def mark_done(self, status: str):
        if self._done_event.is_set():
            # 终态只允许写入一次（并发取消/超时/完成时保证幂等）
            return
        self.status = status
        self.end_time = datetime.now()
        self._done_event.set()

    def to_summary(self) -> str:
        icons = {"queued": "⏳", "running": "🔄", "completed": "✅",
                 "failed": "❌", "cancelled": "⛔", "timeout": "⏰"}
        icon = icons.get(self.status, "?")
        s = f"{icon} [{self.task_id}] {self.description}\n   状态: {self.status} | 耗时: {self.elapsed}"
        if self.status == "queued":
            s += f" | 等待: {self.wait_time}"
        return s


# ============ 任务调度器 ============

class TaskScheduler:
    """智能任务调度器：资源监控 + 并发控制 + 排队"""

    def __init__(self):
        self.active: dict[str, ManagedTask] = {}  # task_id → running task
        self.queue: collections.deque = collections.deque()  # waiting tasks
        self.history: dict[str, ManagedTask] = {}  # finished tasks
        self._lock = threading.RLock()  # 可重入，便于在持锁时安全调用 _move_to_history 等
        self._reader_pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TASKS + 2)
        # 启动后台调度线程
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        logger.info(f"TaskScheduler 启动: max_workers={MAX_CONCURRENT_TASKS}, queue_max={MAX_QUEUE_SIZE}")

    def submit(self, task: ManagedTask) -> tuple:
        """提交任务。Returns: (accepted: bool, message: str)"""
        launch_now = False
        launch_msg = ""
        with self._lock:
            running_count = len(self.active)
            queue_count = len(self.queue)

            # 队列满检查
            if queue_count >= MAX_QUEUE_SIZE:
                return False, f"队列已满 ({queue_count}/{MAX_QUEUE_SIZE})，请等待现有任务完成。"

            # 尝试立即启动
            if running_count < MAX_CONCURRENT_TASKS:
                res_ok, warnings = _resources_ok()
                if res_ok or task.priority == 0:  # 前台任务强制启动
                    # 先占并发槽位，真实启动放到锁外（避免 Popen 耗时阻塞锁）
                    self.active[task.task_id] = task
                    launch_now = True
                    launch_msg = f"任务已启动 (并发: {running_count+1}/{MAX_CONCURRENT_TASKS})"
                else:
                    # 资源不足，入队
                    self.queue.append(task)
                    return True, f"资源不足，已入队等待 (队列: {queue_count+1})。原因: {'; '.join(warnings)}"
            else:
                # 无空闲 slot，入队
                self.queue.append(task)
                return True, f"并发已满 ({running_count}/{MAX_CONCURRENT_TASKS})，已入队 (位置: {queue_count+1})"

        if launch_now:
            # 锁外执行耗时操作（找 exe、写脚本、Popen）
            self._launch(task)
            return True, launch_msg


    def _launch(self, task: ManagedTask):
        """启动一个 MATLAB 子进程执行任务（耗时操作，调用方应在锁外执行）"""
        try:
            matlab_exe = _find_matlab_exe()
        except FileNotFoundError as e:
            task.append_output(f"[错误] {str(e)}")
            task.mark_done("failed")
            with self._lock:
                self.active.pop(task.task_id, None)
            self._move_to_history(task)
            return

        wrapped = _build_wrapped_code(task.code)
        script_path = None

        # 短代码直接通过 -batch 命令行传递（绕过临时文件编码问题）；
        # 长代码写入临时 .m 文件（Windows 下带 UTF-8 BOM）
        if len(wrapped) <= 8000:
            batch_arg = wrapped
        else:
            script_path = _write_temp_script(task.code, task.task_id)
            batch_arg = os.path.splitext(os.path.basename(script_path))[0]

        try:
            proc = subprocess.Popen(
                [matlab_exe, "-batch", batch_arg],
                cwd=task.working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            task.process = proc
            with self._lock:
                task.status = "running"
                task.start_time = datetime.now()
                self.active[task.task_id] = task  # submit 已预登记；_try_dequeue 路径在此补充
            logger.info(f"任务启动: [{task.task_id}] PID={proc.pid}")

            # 启动输出读取线程
            self._reader_pool.submit(self._read_output, task)
            # 启动超时监控线程
            self._reader_pool.submit(self._watch_timeout, task)

        except Exception as e:
            task.append_output(f"[启动失败] {str(e)}")
            task.mark_done("failed")
            with self._lock:
                self.active.pop(task.task_id, None)
            self._move_to_history(task)
            if script_path:
                _cleanup_temp_script(task.task_id)

    def _read_output(self, task: ManagedTask):
        """后台线程：实时读取子进程输出"""
        try:
            for line in task.process.stdout:
                if line:
                    task.append_output(line.rstrip("\n"))
            task.process.wait()
            exit_code = task.process.returncode
            task.exit_code = exit_code

            if task.status == "cancelled":
                pass  # 已被取消
            elif exit_code == 0:
                task.mark_done("completed")
            else:
                if task.status != "timeout":
                    task.mark_done("failed")
            logger.info(f"任务结束: [{task.task_id}] exit={exit_code} 耗时={task.elapsed}")
        except Exception as e:
            task.append_output(f"[输出读取异常] {str(e)}")
            if not task.done:
                task.mark_done("failed")
        finally:
            # 从 active 移除
            with self._lock:
                self.active.pop(task.task_id, None)
            self._move_to_history(task)
            _cleanup_temp_script(task.task_id)

    def _watch_timeout(self, task: ManagedTask):
        """后台线程：超时监控"""
        while not task.done:
            time.sleep(2)
            if task.start_time and task.status == "running":
                elapsed = (datetime.now() - task.start_time).total_seconds()
                if elapsed > task.timeout:
                    logger.warning(f"任务超时: [{task.task_id}] >{task.timeout}s")
                    task.append_output(f"\n[超时] 执行超过 {task.timeout}s 被终止")
                    self.cancel(task.task_id, reason="timeout")
                    return

    def cancel(self, task_id: str, reason: str = "cancelled") -> bool:
        """取消任务（排队中直接移除，运行中杀进程）"""
        with self._lock:
            # 检查队列
            for t in self.queue:
                if t.task_id == task_id:
                    self.queue.remove(t)
                    t.mark_done("cancelled")
                    self._move_to_history(t)
                    return True
            # 检查运行中
            task = self.active.get(task_id)
        if task and task.process:
            try:
                task.process.kill()
            except Exception:
                pass
            task.mark_done("timeout" if reason == "timeout" else "cancelled")
            return True
        return False

    def _move_to_history(self, task: ManagedTask):
        """移入历史记录（最多保留 50 条）"""
        with self._lock:
            self.history[task.task_id] = task
            if len(self.history) > 50:
                oldest = min(self.history.values(), key=lambda t: t.submit_time)
                del self.history[oldest.task_id]

    def _scheduler_loop(self):
        """后台调度循环：每 5s 检查是否可以启动队列中的任务"""
        while True:
            time.sleep(5)
            self._try_dequeue()

    def _try_dequeue(self):
        """尝试从队列中取出任务启动"""
        with self._lock:
            if not self.queue:
                return
            if len(self.active) >= MAX_CONCURRENT_TASKS:
                return
            res_ok, _ = _resources_ok()
            if not res_ok:
                return
            task = self.queue.popleft()
        # 在锁外启动
        self._launch(task)

    def get_task(self, task_id: str) -> ManagedTask:
        """查找任务（active / queue / history）"""
        with self._lock:
            if task_id in self.active:
                return self.active[task_id]
            for t in self.queue:
                if t.task_id == task_id:
                    return t
            return self.history.get(task_id)

    def get_status_summary(self) -> dict:
        with self._lock:
            return {
                "running": len(self.active),
                "queued": len(self.queue),
                "max_concurrent": MAX_CONCURRENT_TASKS,
                "max_queue": MAX_QUEUE_SIZE,
            }


# 全局调度器实例
scheduler = TaskScheduler()


def _join_task_sync(task: "ManagedTask", grace: int = 60) -> bool:
    """同步等待单个任务执行结束，超时则自动取消。

    Returns: True=在超时前进入终态；False=超时（或由看门狗标记为 timeout）且已取消。
    """
    finished = task._done_event.wait(timeout=task.timeout + grace)
    if not finished:
        scheduler.cancel(task.task_id, reason="timeout")
        return False
    if task.status == "timeout":
        return False
    return True


# ============ 执行历史 ============
_execution_history = collections.deque(maxlen=100)
_history_lock = threading.Lock()


def _record_execution(tool: str, code_summary: str, elapsed: float, success: bool, error: str = ""):
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


# ============ 核心执行工具 ============

@mcp.tool()
async def run(code: str, timeout: int = 0, description: str = "") -> str:
    """
    执行 MATLAB 代码并等待完成。每次调用是独立进程，变量不跨调用保持。
    代码必须自包含（自己 load 数据、addpath 等）。

    选择指南:
    - 快速验证 (< 10分钟): 直接调用
    - 长实验 (> 10分钟): 改用 submit_task

    Args:
        code: 要执行的 MATLAB 代码（多行，必须自包含）
        timeout: 超时秒数（0=默认600秒）
        description: 实验描述（可选）

    Returns:
        MATLAB 输出 + 耗时
    """
    t = timeout if timeout > 0 else TASK_TIMEOUT_DEFAULT
    task = ManagedTask(code=code, description=description, timeout=t, priority=0)
    accepted, msg = scheduler.submit(task)

    if not accepted:
        return _error_response("QUEUE_FULL", msg)

    start_time = datetime.now()
    HEARTBEAT = 30

    # 异步等待完成（带心跳保活）
    while not task.done:
        await asyncio.sleep(HEARTBEAT)
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed > t + 60:  # 额外 60s 宽限
            scheduler.cancel(task.task_id, reason="timeout")
            _record_execution("run", code, elapsed, False, "TIMEOUT")
            return _error_response("TIMEOUT",
                f"执行超过 {t}s 被终止（已耗时 {elapsed:.0f}s）。",
                elapsed=elapsed,
                hint="对于更长实验，请使用 submit_task。")
        logger.info(f"run heartbeat: [{task.task_id}] {elapsed:.0f}s elapsed")

    # 完成
    elapsed = (datetime.now() - start_time).total_seconds()
    output = task.get_output()
    success = task.status == "completed"
    _record_execution("run", code, elapsed, success,
                      "" if success else output[-200:] if output else task.status)

    if success:
        time_str = f"{elapsed/3600:.1f}h" if elapsed > 3600 else f"{elapsed/60:.1f}m" if elapsed > 60 else f"{elapsed:.1f}s"
        header = f"[完成] 耗时: {time_str}"
        if description:
            header += f" | {description}"
        return header + "\n" + (truncate_output(output) if output else "[执行完成，无输出]")
    else:
        return _error_response("MATLAB_ERROR" if task.status == "failed" else "TIMEOUT",
                               truncate_output(output) or f"状态: {task.status}",
                               elapsed=elapsed)


@mcp.tool()
def run_script(script_path: str, section: str = "") -> str:
    """
    运行 .m 脚本文件。

    Args:
        script_path: .m 文件路径（绝对或相对于工作目录）
        section: 段落（""=全部, "1"=按索引, "list"=列出段落）

    Returns:
        脚本执行输出
    """
    try:
        resolved = _resolve_workspace_path(script_path)
    except PermissionError:
        return _error_response("PATH_TRANSLATION", f"路径越界，拒绝访问: {script_path}")
    if not os.path.exists(resolved):
        return _error_response("FILE_NOT_FOUND", f"文件不存在: {resolved}")

    if section and section.lower() == "list":
        # 列出段落（先尝试 UTF-8，回退系统编码以兼容 GBK 等旧文件）
        try:
            with open(resolved, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(resolved, "r", encoding="gbk", errors="replace") as f:
                content = f.read()
        sections = []
        for line in content.split("\n"):
            if line.strip().startswith("%%"):
                sections.append(line.strip().lstrip("%").strip())
        if not sections:
            return "[无段落] 文件中没有 %% 分隔符"
        return f"[段落列表] {os.path.basename(resolved)}:\n" + "\n".join(f"  [{i}] {t}" for i, t in enumerate(sections))

    # 构建执行代码
    script_name = os.path.splitext(os.path.basename(resolved))[0]
    if section:
        # 提取指定段落
        try:
            with open(resolved, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(resolved, "r", encoding="gbk", errors="replace") as f:
                content = f.read()
        lines = content.split("\n")
        sec_lines = []
        sec_idx = -1
        current = []
        for line in lines:
            if line.strip().startswith("%%"):
                if current:
                    sec_lines.append(current)
                current = [line]
            else:
                current.append(line)
        if current:
            sec_lines.append(current)
        try:
            sec_idx = int(section)
        except ValueError:
            return _error_response("INVALID_SECTION", f"无法解析段落: '{section}'")
        if sec_idx < 0 or sec_idx >= len(sec_lines):
            return _error_response("INVALID_SECTION", f"段落索引 {sec_idx} 超出范围 (0-{len(sec_lines)-1})")
        code = "\n".join(sec_lines[sec_idx])
    else:
        code = f"run('{_matlab_string_escape(resolved)}')"

    # 同步执行（复用 run 逻辑）
    task = ManagedTask(code=code, timeout=TASK_TIMEOUT_DEFAULT, priority=0)
    scheduler.submit(task)
    if not _join_task_sync(task):
        return _error_response("TIMEOUT", f"执行超时（>{TASK_TIMEOUT_DEFAULT}s），任务已终止")
    output = task.get_output()
    if task.status == "completed":
        return truncate_output(output) or "[执行完成，无输出]"
    return _error_response("MATLAB_ERROR", truncate_output(output) or task.status)


@mcp.tool()
def submit_task(code: str, description: str = "", timeout: int = 0) -> str:
    """
    提交后台 MATLAB 任务，立即返回 task_id。支持真正并行（最多 3 个同时运行）。

    Args:
        code: MATLAB 代码（必须自包含）
        description: 任务描述
        timeout: 超时秒数（0=默认600，长实验设 3600+）

    Returns:
        task_id 和状态
    """
    t = timeout if timeout > 0 else TASK_TIMEOUT_DEFAULT * 6  # 后台默认 3600s
    task = ManagedTask(code=code, description=description, timeout=t, priority=1)
    accepted, msg = scheduler.submit(task)

    if not accepted:
        return _error_response("QUEUE_FULL", msg)

    _record_execution("submit_task", code, 0, True)
    status = scheduler.get_status_summary()
    return (
        f"[任务已提交]\n"
        f"  Task ID: {task.task_id}\n"
        f"  描述: {task.description}\n"
        f"  状态: {task.status}\n"
        f"  超时: {t}s\n"
        f"  并发: {status['running']}/{status['max_concurrent']} | 队列: {status['queued']}\n\n"
        f"监控:\n"
        f"  get_task_status('{task.task_id}')\n"
        f"  get_task_output('{task.task_id}')"
    )


@mcp.tool()
def get_task_status(task_id: str = "") -> str:
    """
    查看任务状态。不阻塞，不占 MATLAB 进程。

    Args:
        task_id: 任务 ID（空=列出所有）
    """
    if not task_id:
        return list_tasks()
    task = scheduler.get_task(task_id)
    if not task:
        return f"[错误] 任务 '{task_id}' 不存在"

    import json
    result = task.to_summary()
    json_block = json.dumps({
        "task_id": task.task_id,
        "status": task.status,
        "elapsed": task.elapsed,
        "wait_time": task.wait_time,
        "has_output": bool(task.get_output()),
    }, ensure_ascii=False)
    result += f"\n---JSON---\n{json_block}"
    return result


@mcp.tool()
def get_task_output(task_id: str, tail_lines: int = 100) -> str:
    """
    获取任务输出（运行中可实时读取）。

    Args:
        task_id: 任务 ID
        tail_lines: 显示最后 N 行（0=全部）
    """
    task = scheduler.get_task(task_id)
    if not task:
        return f"[错误] 任务 '{task_id}' 不存在"

    output = task.get_output(tail=tail_lines)
    if task.status == "running":
        return f"[运行中] 耗时: {task.elapsed}\n{output or '尚无输出'}"
    elif task.status == "queued":
        return f"[排队中] 等待: {task.wait_time}"
    else:
        header = f"[{task.status}] 耗时: {task.elapsed}\n"
        return header + (truncate_output(output) if output else "[无输出]")


@mcp.tool()
def cancel_task(task_id: str) -> str:
    """取消任务（排队中移除，运行中终止进程）。"""
    task = scheduler.get_task(task_id)
    if not task:
        return f"[错误] 任务 '{task_id}' 不存在"
    if task.done:
        return f"[提示] 任务已 {task.status}，无需取消"
    scheduler.cancel(task_id)
    return f"[已取消] 任务 '{task_id}'"


@mcp.tool()
def list_tasks() -> str:
    """列出所有任务（运行中 + 排队 + 最近完成）。"""
    with scheduler._lock:
        active = list(scheduler.active.values())
        queue = list(scheduler.queue)
        recent = sorted(scheduler.history.values(), key=lambda t: t.submit_time)[-10:]
    parts = []
    if active:
        parts.append("[运行中]")
        for t in active:
            parts.append(t.to_summary())
    if queue:
        parts.append("\n[排队中]")
        for t in queue:
            parts.append(t.to_summary())
    if recent:
        parts.append("\n[最近完成]")
        for t in reversed(recent):
            parts.append(t.to_summary())
    if not parts:
        return "[无任务] 使用 run 或 submit_task 执行 MATLAB 代码。"
    return "\n".join(parts)


@mcp.tool()
def get_history(n: int = 20) -> str:
    """查看最近执行历史。"""
    with _history_lock:
        records = list(_execution_history)
    if not records:
        return "[无执行历史]"
    n = min(n, len(records))
    recent = records[-n:]
    recent.reverse()
    result = f"[执行历史] 最近 {n} 条\n\n"
    for i, r in enumerate(recent, 1):
        icon = "✓" if r["success"] else "✗"
        code_preview = r["code"].replace("\n", " ")[:60]
        result += f"  {i:2d}. {icon} [{r['time']}] {r['tool']} | {r['elapsed_s']}s\n      {code_preview}\n"
    return result


# ============ 实验工具 ============

@mcp.tool()
def experiment(algo: str = "HeteroPSO-KR", models: str = "1:56", n_runs: int = 1,
               output_base: str = "", extra_params: str = "", seed: int = 42,
               raw_code: str = "") -> str:
    """
    运行论文实验。两种模式: 参数化 或 raw_code。

    Args:
        algo: 算法名称
        models: 模型范围 (如 '1:56')
        n_runs: 每模型重复次数
        output_base: 输出目录
        extra_params: 额外参数 ('n=10, maxevals=30000')
        seed: 随机种子
        raw_code: 原始 MATLAB 代码（设置后忽略其他参数）
    """
    if raw_code:
        code = raw_code
    else:
        if not output_base:
            output_base = f"results_matlab/mcp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        extra_opts = "struct()"
        if extra_params:
            pairs = []
            for p in extra_params.split(","):
                p = p.strip()
                if "=" in p:
                    k, v = p.split("=", 1)
                    pairs.append(f"'{k.strip()}', {v.strip()}")
            if pairs:
                extra_opts = f"struct({', '.join(pairs)})"
        algo_esc = algo.replace("'", "''")
        output_base_esc = output_base.replace("'", "''")
        code = f"""
addpath(fullfile(pwd, 'aux_files'));
addpath(fullfile(pwd, 'methods'));
addpath(fullfile(pwd, 'utils'));
mcpOpts = struct();
mcpOpts.algo = '{algo_esc}';
mcpOpts.models = {models};
mcpOpts.n_runs = {n_runs};
mcpOpts.output_dir = '{output_base_esc}';
mcpOpts.seed = {seed};
mcpOpts.extra_opts = {extra_opts};
mcp_run_experiment(mcpOpts);
"""
    # 作为后台任务提交
    task = ManagedTask(code=code, description=f"experiment: {algo} models={models}",
                       timeout=TASK_TIMEOUT_DEFAULT * 6, priority=1)
    scheduler.submit(task)
    return f"[实验已提交] Task ID: {task.task_id}\n使用 get_task_status('{task.task_id}') 监控进度。"


# ============ 文件检查工具 ============

@mcp.tool()
def inspect(file_path: str) -> str:
    """
    检查 .mat 文件内容（变量名、大小、类型）。

    Args:
        file_path: .mat 文件路径（绝对或相对于工作目录）
    """
    try:
        resolved = _resolve_workspace_path(file_path)
    except PermissionError:
        return _error_response("PATH_TRANSLATION", f"路径越界，拒绝访问: {file_path}")
    if not os.path.exists(resolved):
        return _error_response("FILE_NOT_FOUND", f"文件不存在: {resolved}")

    code = f"whos('-file', '{_matlab_string_escape(resolved)}')"
    task = ManagedTask(code=code, timeout=120, priority=0)
    scheduler.submit(task)
    if not _join_task_sync(task):
        return _error_response("TIMEOUT", f"检查超时（>{task.timeout}s），任务已终止")
    output = task.get_output()
    if task.status == "completed":
        return f"[文件: {os.path.basename(resolved)}]\n{output}"
    return _error_response("MATLAB_ERROR", output or "检查失败")


@mcp.tool()
def lint_code(code: str = "", file_path: str = "") -> str:
    """
    MATLAB checkcode 静态分析。

    Args:
        code: 要检查的代码（与 file_path 二选一）
        file_path: 要检查的 .m 文件路径
    """
    if file_path:
        try:
            resolved = _resolve_workspace_path(file_path)
        except PermissionError:
            return _error_response("PATH_TRANSLATION", f"路径越界，拒绝访问: {file_path}")
        if not os.path.exists(resolved):
            return _error_response("FILE_NOT_FOUND", f"文件不存在: {resolved}")
        matlab_code = f"""
issues = checkcode('{_matlab_string_escape(resolved)}');
if isempty(issues), fprintf('未发现问题\\n');
else
  fprintf('发现 %d 个问题:\\n', length(issues));
  for i = 1:length(issues), fprintf('  L%d: %s\\n', issues(i).line, issues(i).message); end
end"""
    elif code:
        # 写入临时文件再检查
        tmp = os.path.join(MATLAB_WORKING_DIR, "_mcp_lint_tmp.m")
        with open(tmp, "w", encoding=_matlab_script_encoding()) as f:
            f.write(code)
        tmp_esc = _matlab_string_escape(tmp)
        matlab_code = f"""
issues = checkcode('{tmp_esc}');
if isempty(issues), fprintf('未发现问题\\n');
else
  fprintf('发现 %d 个问题:\\n', length(issues));
  for i = 1:length(issues), fprintf('  L%d: %s\\n', issues(i).line, issues(i).message); end
end
delete('{tmp_esc}');"""
    else:
        return "[错误] 请提供 code 或 file_path"

    task = ManagedTask(code=matlab_code, timeout=120, priority=0)
    scheduler.submit(task)
    if not _join_task_sync(task):
        return _error_response("TIMEOUT", f"检查超时（>{task.timeout}s），任务已终止")
    return truncate_output(task.get_output()) or "[检查完成]"


# ============ 文件工具 ============

@mcp.tool()
def list_files(directory: str = ".", pattern: str = "*") -> str:
    """列出远程目录文件。"""
    try:
        d = MATLAB_WORKING_DIR if directory == "." else _resolve_workspace_path(directory)
        if not os.path.exists(d):
            return f"[错误] 目录不存在: {d}"
        files = []
        for f in sorted(Path(d).glob(pattern)):
            if f.is_file():
                size = f.stat().st_size
                mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                sz = f"{size/1024/1024:.1f} MB" if size > 1024*1024 else f"{size/1024:.1f} KB" if size > 1024 else f"{size} B"
                files.append(f"  {f.name:<40} {sz:>10}  {mtime}")
        if not files:
            return f"[目录 {d} 中没有匹配 '{pattern}' 的文件]"
        return f"[目录: {d}] ({len(files)} 个文件)\n" + "\n".join(files)
    except Exception as e:
        return f"[错误] {str(e)}"


@mcp.tool()
def transfer_file(file_path: str) -> str:
    """读取 Windows 端文件，返回 base64。限 50MB。"""
    try:
        resolved = _resolve_workspace_path(file_path)
    except PermissionError:
        return _error_response("PATH_TRANSLATION", f"路径越界，拒绝访问: {file_path}")
    if not os.path.exists(resolved):
        return f"[错误] 文件不存在: {resolved}"
    size = os.path.getsize(resolved)
    if size > MAX_TRANSFER_BYTES:
        return f"[错误] 文件过大: {size/1024/1024:.1f}MB (限 50MB)"
    with open(resolved, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"[文件: {os.path.basename(resolved)}] ({size} bytes)\n[BASE64_START]\n{data}\n[BASE64_END]"


@mcp.tool()
def upload_file(file_path: str, base64_data: str) -> str:
    """将 base64 数据写入 Windows 端文件。"""
    try:
        resolved = _resolve_workspace_path(file_path)
    except PermissionError:
        return _error_response("PATH_TRANSLATION", f"路径越界，拒绝访问: {file_path}")
    try:
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        data = base64.b64decode(base64_data)
        if len(data) > MAX_TRANSFER_BYTES:
            return _error_response("FILE_TOO_LARGE", f"数据过大: {len(data)/1024/1024:.1f}MB (限 {MAX_TRANSFER_BYTES//1024//1024}MB)")
        with open(resolved, "wb") as f:
            f.write(data)
        return f"[成功] 已写入: {resolved} ({len(data)} bytes)"
    except Exception as e:
        return f"[错误] {str(e)}"


# ============ 图形工具 ============

@mcp.tool()
def save_figure(figure_code: str, filename: str = "", format: str = "png", dpi: int = 200) -> str:
    """
    执行出图代码并保存到 exports/（通过 Syncthing 同步到 Mac）。

    Args:
        figure_code: 生成图形的 MATLAB 代码
        filename: 文件名（不含扩展名，默认自动生成）
        format: 格式 (png/svg/pdf)
        dpi: 分辨率
    """
    if not filename:
        filename = f"figure_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    filename = os.path.basename(filename)  # 防目录穿越
    export_path = f"exports/{filename}.{format}"
    export_path_esc = _matlab_string_escape(export_path)
    code = f"""
{figure_code}
if ~exist('exports', 'dir'), mkdir('exports'); end
exportgraphics(gcf, '{export_path_esc}', 'Resolution', {dpi});
fprintf('图片已保存: {export_path_esc}\\n');
"""
    task = ManagedTask(code=code, timeout=300, priority=0)
    scheduler.submit(task)
    if not _join_task_sync(task):
        return _error_response("TIMEOUT", f"出图超时（>{task.timeout}s），任务已终止")
    output = task.get_output()
    if task.status == "completed":
        full_path = _resolve_workspace_path(export_path)
        return f"[图片已保存] {full_path}\n通过 Syncthing 同步到 Mac 后读取。"
    return _error_response("MATLAB_ERROR", output or "出图失败")


# ============ 系统工具 ============

@mcp.tool()
def diagnose(detail: str = "full") -> str:
    """
    诊断服务器状态。

    Args:
        detail: "quick" (资源) 或 "full" (含 MATLAB/Syncthing)
    """
    import json
    res = _get_system_resources()
    status = scheduler.get_status_summary()
    res_ok, warnings = _resources_ok()

    lines = ["[服务器诊断 v3.0]"]
    lines.append(f"\n  [资源]")
    lines.append(f"    CPU: {res['cpu_percent']:.0f}% (阈值 {CPU_THRESHOLD:.0f}%)")
    lines.append(f"    内存: {res['memory_percent']:.0f}% (阈值 {MEMORY_THRESHOLD:.0f}%)")
    if res['memory_total_gb'] > 0:
        lines.append(f"    可用: {res['memory_available_gb']} GB / {res['memory_total_gb']} GB")
    lines.append(f"    磁盘: {res['disk_percent']:.0f}%")

    lines.append(f"\n  [任务调度]")
    lines.append(f"    运行中: {status['running']}/{status['max_concurrent']}")
    lines.append(f"    排队中: {status['queued']}/{status['max_queue']}")
    lines.append(f"    历史: {len(scheduler.history)} 条")

    if detail == "full":
        lines.append(f"\n  [组件]")
        try:
            matlab = _find_matlab_exe()
            lines.append(f"    ✓ MATLAB: {matlab}")
        except FileNotFoundError:
            lines.append(f"    ✗ MATLAB: 未找到")
        lines.append(f"    ✓ 工作目录: {MATLAB_WORKING_DIR}")
        lines.append(f"    ✓ 传输: Streamable HTTP")

    lines.append(f"\n  [结论] {'✓ 可接受新任务' if res_ok else '⚠ 资源紧张: ' + '; '.join(warnings)}")

    json_block = json.dumps({
        "cpu_percent": res["cpu_percent"], "memory_percent": res["memory_percent"],
        "tasks_running": status["running"], "tasks_queued": status["queued"],
        "can_accept_task": res_ok and status["queued"] < MAX_QUEUE_SIZE,
    }, ensure_ascii=False)
    lines.append(f"\n---JSON---\n{json_block}")
    return "\n".join(lines)


@mcp.tool()
def sync_status() -> str:
    """检查 Syncthing 文件同步状态。"""
    import urllib.request
    import json
    syncthing_url = os.environ.get("SYNCTHING_URL", "http://127.0.0.1:8384")
    from urllib.parse import urlparse
    parsed = urlparse(syncthing_url)
    api_key = parsed.password
    base_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 8384}"
    try:
        req = urllib.request.Request(f"{base_url}/rest/system/status")
        req.add_header("Accept", "application/json")
        if api_key:
            req.add_header("X-API-Key", api_key)
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = json.loads(resp.read())
        my_id = status.get("myID", "?")[:12]
        req2 = urllib.request.Request(f"{base_url}/rest/system/connections")
        req2.add_header("Accept", "application/json")
        if api_key:
            req2.add_header("X-API-Key", api_key)
        with urllib.request.urlopen(req2, timeout=5) as resp2:
            conns = json.loads(resp2.read())
        connections = conns.get("connections", {})
        result = f"[Syncthing] ID: {my_id}...\n"
        for dev_id, info in connections.items():
            icon = "✓" if info.get("connected") else "✗"
            result += f"  {icon} 设备 {dev_id[:12]}...\n"
        return result
    except Exception as e:
        return f"[Syncthing 不可用] {str(e)}\n配置: {syncthing_url}"


# ============ 启动 ============
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MATLAB MCP Server v3.0 (子进程池架构)")
    parser.add_argument("--workdir", default=None, help="MATLAB 工作目录")
    parser.add_argument("--transport", choices=["streamable-http", "sse"], default="streamable-http")
    args = parser.parse_args()

    if args.workdir:
        MATLAB_WORKING_DIR = args.workdir

    TRANSPORT = os.environ.get("MCP_TRANSPORT", args.transport)
    endpoint = "/mcp" if TRANSPORT == "streamable-http" else "/sse"

    logger.info("=" * 60)
    logger.info("MATLAB MCP Server v3.0 启动 (子进程池架构)")
    logger.info(f"  传输: {TRANSPORT} | 端点: http://{HOST}:{PORT}{endpoint}")
    logger.info(f"  健康: http://{HOST}:{PORT}/health")
    logger.info(f"  工作目录: {MATLAB_WORKING_DIR}")
    logger.info(f"  并发: {MAX_CONCURRENT_TASKS} | 队列: {MAX_QUEUE_SIZE}")
    logger.info(f"  认证: {'已启用' if MCP_TOKEN else '未启用'}")
    try:
        logger.info(f"  MATLAB: {_find_matlab_exe()}")
    except FileNotFoundError:
        logger.error("  MATLAB: 未找到！请设置 MATLAB_EXE")
        sys.exit(1)
    logger.info("=" * 60)

    # 启动服务
    import uvicorn
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.types import ASGIApp, Receive, Scope, Send

    async def health_check(request: Request):
        status = scheduler.get_status_summary()
        res = _get_system_resources()
        return JSONResponse({
            "status": "ok",
            "version": "3.0",
            "transport": TRANSPORT,
            "tasks_running": status["running"],
            "tasks_queued": status["queued"],
            "max_concurrent": status["max_concurrent"],
            "cpu_percent": res["cpu_percent"],
            "memory_percent": res["memory_percent"],
        })

    class BearerTokenMiddleware:
        def __init__(self, app: ASGIApp, token: str):
            self.app = app
            self.token = token

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
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
                    authenticated = hmac.compare_digest(supplied, self.token)
                if not authenticated:
                    resp = JSONResponse({"error": "Unauthorized"}, status_code=401)
                    await resp(scope, receive, send)
                    return
            await self.app(scope, receive, send)

    # 获取 MCP ASGI app
    if TRANSPORT == "streamable-http":
        try:
            mcp_app = mcp.streamable_http_app()
        except AttributeError:
            logger.warning("SDK 不支持 streamable_http_app()，回退 SSE")
            mcp_app = mcp.sse_app()
    else:
        mcp_app = mcp.sse_app()

    # 健康检查路由直接挂到 MCP app 上，不能用外层 Starlette 包裹 Mount：
    # 外层 app 会接管 lifespan，导致 MCP 子应用的 lifespan 不触发，
    # StreamableHTTPSessionManager 未初始化，所有 /mcp 请求返回 500。
    mcp_app.routes.append(Route("/health", health_check))

    if MCP_TOKEN:
        mcp_app = BearerTokenMiddleware(mcp_app, MCP_TOKEN)

    uvicorn.run(mcp_app, host=HOST, port=PORT, log_level="warning")
