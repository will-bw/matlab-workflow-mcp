"""
MATLAB MCP Server v3.0 配置文件
=================================
基于 matlab -batch 子进程池架构。
修改此文件适配你的 Windows 环境。
所有配置项也可通过环境变量覆盖。
"""

import os

# ============ MATLAB 配置 ============
# MATLAB 项目工作目录
MATLAB_WORKING_DIR = os.environ.get(
    "MATLAB_WORKING_DIR",
    r"E:\code\Paper2"
)

# MATLAB 可执行文件路径（留空则自动从 PATH 查找）
MATLAB_EXE = os.environ.get(
    "MATLAB_EXE",
    r"C:\Program Files\MATLAB\R2022b\bin\matlab.exe"
)

# ============ 网络配置 ============
HOST = os.environ.get("MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", "8080"))

# ============ 任务调度配置 ============
# 最大并发 MATLAB 进程数（32GB 内存建议 3 个，每个约占 1GB）
MAX_CONCURRENT_TASKS = int(os.environ.get("MAX_CONCURRENT_TASKS", "3"))

# 最大排队任务数（超过则拒绝提交）
MAX_QUEUE_SIZE = int(os.environ.get("MAX_QUEUE_SIZE", "5"))

# 默认任务超时（秒）
TASK_TIMEOUT_DEFAULT = int(os.environ.get("TASK_TIMEOUT_DEFAULT", "600"))

# ============ 资源阈值 ============
# CPU 使用率超过此值时不再启动新任务
CPU_THRESHOLD = float(os.environ.get("CPU_THRESHOLD", "90"))

# 内存使用率超过此值时不再启动新任务
MEMORY_THRESHOLD = float(os.environ.get("MEMORY_THRESHOLD", "90"))

# 可用内存低于此值(GB)时不再启动新 MATLAB 进程
# 16GB 机器建议 4；防止内存耗尽导致 MATLAB 堆损坏崩溃(0xC0000374)
MIN_FREE_MEMORY_GB = float(os.environ.get("MIN_FREE_MEMORY_GB", "4"))

# 磁盘使用率超过此值时警告
DISK_THRESHOLD = float(os.environ.get("DISK_THRESHOLD", "95"))

# ============ 输出配置 ============
MAX_OUTPUT_LENGTH = int(os.environ.get("MAX_OUTPUT_LENGTH", "50000"))

# ============ 认证配置 ============
# Bearer Token（空=不启用认证）
MCP_TOKEN = os.environ.get("MCP_TOKEN", "")

# ============ 客户端配置示例 ============
CLIENT_CONFIG_EXAMPLE = """
在 Qoder 的 MCP 配置中添加:

{
  "mcpServers": {
    "matlab": {
      "type": "http",
      "url": "http://100.x.y.z:8080/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_TOKEN>"
      }
    }
  }
}

注: 传输为 Streamable HTTP（端点 /mcp），认证走请求头 Authorization: Bearer。
"""
