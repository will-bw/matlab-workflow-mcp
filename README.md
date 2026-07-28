# MATLAB MCP Server

跨平台 MATLAB 远程实验执行服务。在 Mac 端通过 Qoder/QoderWork 用自然语言驱动 Windows 端 MATLAB 执行 UAV 路径规划实验。

## 架构

```
Mac (Qoder IDE)                         Windows (MATLAB R2022b)
┌───────────────────┐                  ┌──────────────────────────────┐
│  MCP Client (SSE) │ ─── Tailscale ──►│  matlab_mcp_server.py        │
│  Syncthing        │ ◄── P2P Sync ───►│  MATLAB Engine (持久会话)     │
│  Git              │                  │  21 个 MCP 工具              │
└───────────────────┘                  └──────────────────────────────┘
```

- **执行层**: MCP over SSE (:8080)，支持 Bearer Token + query param 认证
- **同步层**: Syncthing P2P (:22000)，代码实时双向同步
- **网络层**: Tailscale (WireGuard)，局域网/公网自动切换

## 快速开始

### Windows 端

```powershell
# 1. 安装 MATLAB Engine API
cd "C:\Program Files\MATLAB\R2022b\extern\engines\python"
python setup.py install

# 2. 安装依赖
pip install -r requirements.txt

# 3. 修改 .env 配置（MATLAB_WORKING_DIR 等）

# 4. 启动服务
python matlab_mcp_server.py
# 或双击 start_server.bat
```

### Mac 端 (Qoder MCP 配置)

```json
{
  "mcpServers": {
    "matlab": {
      "type": "sse",
      "url": "http://100.x.y.z:8080/sse?token=YOUR_TOKEN"
    }
  }
}
```

## 工具清单 (21 个)

| 类别 | 工具 | 说明 |
|------|------|------|
| 执行 | `run` | 执行代码（自动捕获图形，含耗时统计） |
| 执行 | `run_script` | 运行 .m 脚本或指定段落 |
| 执行 | `submit_task` | 提交异步后台任务（>30分钟实验） |
| 实验 | `experiment` | 参数化实验 + raw_code 双模式 |
| 任务 | `get_task_status` / `get_task_output` / `cancel_task` / `list_tasks` | 后台任务生命周期管理 |
| 工作区 | `inspect` | 查看工作区/变量值/struct 结构 |
| 工作区 | `set_variable` | 设置变量 |
| 图形 | `save_figure` / `get_figure_info` | 导出图形 / 获取元数据 |
| 文件 | `transfer_file` / `upload_file` / `list_files` | 文件传输与管理 |
| 质量 | `lint_code` | MATLAB checkcode 静态检查 |
| 诊断 | `diagnose` | 系统诊断（quick/full） |
| 管理 | `sync_status` / `reset_session` / `change_directory` / `force_restart_engine` | 同步/重置/切换/重启 |

### 工具选择指南

| 实验时长 | 推荐工具 |
|----------|----------|
| < 10 分钟 | `run` |
| 10 - 30 分钟 | `run(timeout=1800)` |
| > 30 分钟 | `submit_task` |
| 论文标准实验 | `experiment` |

## 项目结构

```
├── matlab_mcp_server.py      # 主服务（21 个 MCP 工具，~1879 行）
├── mcp_run_experiment.m      # MATLAB 实验执行器（含 manifest + 种子管理）
├── cleanup_and_start.py      # 安全启动器（清理残留进程）
├── config.py                 # 配置兜底
├── .env                      # 环境变量配置（优先级最高）
├── requirements.txt          # Python 依赖
├── test_smoke.py             # 冒烟测试（19 个用例）
│
├── start_server.bat          # Windows 快速启动
├── install_service.bat       # NSSM 服务安装（开机自启）
├── setup_firewall.ps1        # Windows 防火墙配置
├── setup_syncthing_mac.sh    # Mac Syncthing 配置
├── setup_syncthing_win.ps1   # Windows Syncthing 配置
├── sync_and_run.sh           # Mac 一键同步+运行
├── fetch_results.sh          # Mac 结果拉取
├── test_connection.py        # 连接测试
│
├── DEPLOYMENT_GUIDE.md       # 部署操作手册（16 章）
├── SOLUTION_REPORT.md        # 方案讲解报告
├── .qoder/skills/            # Qoder AI Skill（工具选择指导）
└── .gitattributes            # Git LFS 配置
```

## 配置优先级

环境变量 > `.env` 文件 > `config.py` > 代码默认值

关键配置项（在 `.env` 中设置）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MATLAB_WORKING_DIR` | `E:\code\Paper2` | MATLAB 工作目录 |
| `MCP_HOST` | `0.0.0.0` | 监听地址 |
| `MCP_PORT` | `8080` | 监听端口 |
| `MCP_TOKEN` | (空) | Bearer Token 认证 |
| `EXEC_TIMEOUT` | `600` | 默认执行超时（秒） |
| `MAX_QUEUE_SIZE` | `5` | 最大排队任务数 |
| `CPU_THRESHOLD` | `90` | CPU 拒绝阈值 (%) |
| `MEMORY_THRESHOLD` | `85` | 内存拒绝阈值 (%) |
| `LOG_DIR` | 脚本所在目录 | 日志输出目录 |

## 运行测试

```bash
python test_smoke.py
```

## 技术栈

- Python 3.8-3.10 + MATLAB Engine API (R2022b)
- MCP SDK (FastMCP) + SSE transport
- Tailscale (WireGuard) + Syncthing
- NSSM (Windows 服务) + Git LFS

## 文档

- [部署操作手册](DEPLOYMENT_GUIDE.md) — 从零到可用的完整指南
- [方案讲解报告](SOLUTION_REPORT.md) — 架构设计与决策理由
