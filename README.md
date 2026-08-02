# MATLAB MCP Server

跨平台 MATLAB 远程实验执行服务。在 Mac 端通过 Qoder/QoderWork 用自然语言驱动 Windows 端 MATLAB 执行 UAV 路径规划实验。

## 架构

```
Mac (Qoder IDE)                         Windows (MATLAB R2022b)
┌───────────────────┐                  ┌──────────────────────────────┐
│  MCP Client (HTTP)│ ─── Tailscale ──►│  matlab_mcp_server.py        │
│  Syncthing        │ ◄── P2P Sync ───►│  子进程池 + matlab -batch    │
│  Git              │                  │  17 个 MCP 工具              │
└───────────────────┘                  └──────────────────────────────┘
```

- **执行层**: 子进程池 + `matlab -batch`（Streamable HTTP, :8080），独立进程真正并行，无持久 Engine 会话
- **同步层**: Syncthing P2P (:22000)，代码实时双向同步
- **网络层**: Tailscale (WireGuard)，局域网/公网自动切换

## 快速开始

### Windows 端

```powershell
# 1. 安装依赖（无需 MATLAB Engine API）
pip install -r requirements.txt

# 2. 修改 .env 配置（MATLAB_WORKING_DIR、PYTHON_PATH、MCP_TOKEN 等）
#    matlab 需在 PATH 中，或通过 .env 的 MATLAB_EXE 指定

# 3. 启动服务
python matlab_mcp_server.py
# 或双击 start_server.bat
```

### Mac 端 (Qoder MCP 配置)

```json
{
  "mcpServers": {
    "matlab": {
      "type": "http",
      "url": "http://100.x.y.z:8080/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

> 认证仅走请求头 `Authorization: Bearer`，不支持 query 参数携带 token。

## 工具清单 (17 个)

| 类别 | 工具 | 说明 |
|------|------|------|
| 执行 | `run` | 执行代码（自动捕获图形，含耗时统计） |
| 执行 | `run_script` | 运行 .m 脚本或指定段落 |
| 执行 | `submit_task` | 提交异步后台任务（>30分钟实验） |
| 实验 | `experiment` | 参数化实验 + raw_code 双模式 |
| 任务 | `get_task_status` / `get_task_output` / `cancel_task` / `list_tasks` | 后台任务生命周期管理 |
| 历史 | `get_history` | 查看已完成任务历史记录 |
| 工作区 | `inspect` | 查看 .m 脚本/工作区变量/struct 结构 |
| 图形 | `save_figure` | 导出图形 |
| 文件 | `transfer_file` / `upload_file` / `list_files` | 文件传输与管理 |
| 质量 | `lint_code` | MATLAB checkcode 静态检查 |
| 诊断 | `diagnose` | 系统诊断（quick/full） |
| 管理 | `sync_status` | 同步状态检查 |

### 工具选择指南

| 实验时长 | 推荐工具 |
|----------|----------|
| < 10 分钟 | `run` |
| 10 - 30 分钟 | `run(timeout=1800)` |
| > 30 分钟 | `submit_task` |
| 论文标准实验 | `experiment` |

## 项目结构

```
├── matlab_mcp_server.py      # 主服务（17 个 MCP 工具，~1150 行）
├── mcp_run_experiment.m      # MATLAB 实验执行器（含 manifest + 种子管理）
├── cleanup_and_start.py      # 安全启动器（清理残留的 matlab -batch 进程）
├── config.py                 # 配置兜底（.env 为唯一权威）
├── .env                      # 环境变量配置（唯一权威，不入库）
├── requirements.txt          # Python 依赖
├── test_smoke.py             # 冒烟测试（调度器/认证/路径沙箱）
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

`.env` 文件为**唯一权威**配置源，`config.py` 仅作兜底默认值。

关键配置项（在 `.env` 中设置）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MATLAB_WORKING_DIR` | `E:\code\Paper2` | MATLAB 工作目录 |
| `MCP_HOST` | `0.0.0.0` | 监听地址 |
| `MCP_PORT` | `8080` | 监听端口 |
| `MCP_TOKEN` | (空) | Bearer Token 认证（强烈建议设置） |
| `TASK_TIMEOUT_DEFAULT` | `600` | 默认执行超时（秒） |
| `MAX_CONCURRENT_TASKS` | `3` | 最大并发 MATLAB 进程数 |
| `MAX_QUEUE_SIZE` | `5` | 最大排队任务数 |
| `CPU_THRESHOLD` | `90` | CPU 拒绝阈值 (%) |
| `MEMORY_THRESHOLD` | `90` | 内存拒绝阈值 (%) |
| `DISK_THRESHOLD` | `95` | 磁盘警告阈值 (%) |
| `LOG_DIR` | 脚本目录\logs | 日志输出目录 |

## 技术栈

- Python 3.9+（无需 MATLAB Engine API）
- MCP SDK (FastMCP) + Streamable HTTP transport
- Tailscale (WireGuard) + Syncthing
- NSSM (Windows 服务) + Git LFS

## 运行测试

```bash
python test_smoke.py   # 冒烟测试（含调度器/认证/路径沙箱）
python test_connection.py --token YOUR_TOKEN   # 连接测试（真实握手）
```

## 文档

- [部署操作手册](DEPLOYMENT_GUIDE.md) — 从零到可用的完整指南
- [方案讲解报告](SOLUTION_REPORT.md) — 架构设计与决策理由
