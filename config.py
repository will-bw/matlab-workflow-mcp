"""
MATLAB MCP Server 配置文件
===========================
修改此文件适配你的 Windows 环境。
所有配置项也可通过环境变量覆盖。
"""

import os

# ============ MATLAB 配置 ============
# MATLAB 项目工作目录（Paper2 项目路径）
MATLAB_WORKING_DIR = os.environ.get(
    "MATLAB_WORKING_DIR",
    r"E:\code\Paper2"  # <-- 修改为你的实际路径
)

# MATLAB 安装路径（用于 Engine API 安装参考）
MATLAB_ROOT = os.environ.get(
    "MATLAB_ROOT",
    r"C:\Program Files\MATLAB\R2022b"  # <-- 修改为你的 MATLAB 安装路径
)

# ============ 网络配置 ============
# 服务监听地址（0.0.0.0 表示监听所有网络接口）
HOST = os.environ.get("MCP_HOST", "0.0.0.0")

# 服务端口
PORT = int(os.environ.get("MCP_PORT", "8080"))

# ============ 输出配置 ============
# 单次工具调用最大输出字符数（防止传输超时）
MAX_OUTPUT_LENGTH = int(os.environ.get("MAX_OUTPUT_LENGTH", "50000"))

# ============ Tailscale 配置（参考） ============
# 安装 Tailscale 后，Windows 会获得一个 100.x.y.z 的虚拟 IP
# Mac 端 MCP 客户端配置中使用该 IP 即可实现公网连接
# 示例: http://100.x.y.z:8080/sse
TAILSCALE_NOTE = """
Tailscale 配置步骤:
1. Windows 和 Mac 各安装 Tailscale: https://tailscale.com/download
2. 两端用同一账号登录
3. 在 Tailscale 管理面板查看 Windows 的 Tailscale IP (100.x.y.z)
4. Mac 端 MCP 配置使用: http://100.x.y.z:8080/sse
"""

# ============ 客户端配置示例 ============
CLIENT_CONFIG_EXAMPLE = """
在 Qoder/QoderWork 的 MCP 配置中添加:

局域网场景:
{
  "mcpServers": {
    "matlab": {
      "type": "sse",
      "url": "http://192.168.1.100:8080/sse"
    }
  }
}

公网场景 (Tailscale):
{
  "mcpServers": {
    "matlab": {
      "type": "sse",
      "url": "http://100.x.y.z:8080/sse"
    }
  }
}
"""
