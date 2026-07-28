# MATLAB MCP Server 部署操作手册

> 从零开始到完整可用的详细指南。Windows 端运行 MATLAB 服务，Mac 端通过 Qoder/QoderWork 远程调用。
>
> 适用版本：matlab_mcp_server.py（21 个工具）| 更新日期：2026-07-28

---

## 目录

1. [系统架构](#一系统架构)
2. [环境准备（Windows 端）](#二环境准备windows-端)
3. [安装 MATLAB Engine API](#三安装-matlab-engine-api)
4. [部署 MCP Server](#四部署-mcp-server)
5. [网络配置（Tailscale）](#五网络配置tailscale)
6. [防火墙配置](#六防火墙配置)
7. [认证配置](#七认证配置)
8. [Mac 端客户端配置](#八mac-端客户端配置)
9. [开机自启动配置](#九开机自启动配置)
10. [Syncthing 代码同步](#十syncthing-代码同步)
11. [Git 版本控制工作流](#十一git-版本控制工作流)
12. [功能接口说明](#十二功能接口说明)
13. [使用示例](#十三使用示例)
14. [实验迭代操作流程](#十四实验迭代操作流程)
15. [故障排查与调试](#十五故障排查与调试)
16. [后续扩展方案](#十六后续扩展方案)

---

## 一、系统架构

```
Mac (Qoder / QoderWork)                    Windows PC
┌─────────────────────┐                   ┌──────────────────────────────────────┐
│  MCP Client (SSE)   │   HTTP/SSE       │  matlab_mcp_server.py                │
│                     │ ───────────────►  │    ├─ FastMCP (SSE transport)        │
│  局域网: 直连 IP    │                   │    ├─ Bearer Token 认证中间件         │
│  公网: Tailscale IP │                   │    ├─ 21 个工具 (执行/查询/实验/管理) │
│                     │                   │    └─ MATLAB Engine (持久会话)        │
└─────────────────────┘                   └──────────────────────────────────────┘
        │                                                │
        │          Syncthing (代码双向同步)               │
        └────────────── ════════════════ ────────────────┘
                     ~/Desktop/codes/Paper2  ◄══►  E:\code\Paper2
```

**核心特性：**
- 持久 MATLAB 会话：变量不丢失，支持连续交互
- SSE 传输：支持局域网和 Tailscale 公网
- 统一加锁：所有 MATLAB Engine 调用经 `matlab_eval` 串行化，前台工具与后台任务不会并发冲突
- 可选认证：Bearer Token（header 或 `?token=` query parameter）
- 实验元数据：每次实验自动生成 `manifest.json`（算法/种子/git commit/参数快照）
- 为 Paper2 (UAV 4D 路径规划) 项目定制

---

## 二、环境准备（Windows 端）

### 2.1 安装 Python 3.10

> MATLAB R2022b 支持 Python 3.8–3.10，推荐 3.10。

1. 下载: https://www.python.org/downloads/release/python-31011/
2. 安装时勾选 **"Add Python to PATH"**
3. 验证:
```powershell
python --version
# 应输出: Python 3.10.11
```

### 2.2 确认 MATLAB 安装

确保 MATLAB R2022b 已安装，记住安装路径（默认 `C:\Program Files\MATLAB\R2022b`）。

### 2.3 确认项目路径

确保 Paper2 项目已存在于 Windows 上，如 `E:\code\Paper2`。

---

## 三、安装 MATLAB Engine API

在 PowerShell 中执行：

```powershell
# 进入 MATLAB Engine 目录（根据实际安装路径调整）
cd "C:\Program Files\MATLAB\R2022b\extern\engines\python"

# 安装 Engine API
python setup.py install
```

**验证安装：**
```powershell
python -c "import matlab.engine; print('MATLAB Engine API OK')"
```

> 如果报错，检查:
> - Python 版本是否为 3.8-3.10
> - 是否使用了正确的 python 命令（可能需要 `py -3.10`）
> - MATLAB 路径是否正确

---

## 四、部署 MCP Server

### 4.1 复制文件到 Windows

将项目所有文件复制到 Windows 的某个目录（如 `E:\code\WinServerBuild\`）：

```
E:\code\WinServerBuild\
├── matlab_mcp_server.py      # 主服务（21 个工具）
├── cleanup_and_start.py      # 安全启动器（清理残留进程 + 启动主服务）
├── mcp_run_experiment.m      # MATLAB 实验执行器（由 run_experiment 调用）
├── config.py                 # 配置兜底（环境变量 > .env > config.py > 默认值）
├── .env                      # 统一环境配置（优先修改此文件）
├── requirements.txt          # Python 依赖
├── start_server.bat          # 快速启动脚本（自动读取 .env）
├── install_service.bat       # NSSM 服务安装脚本
├── setup_firewall.ps1        # 防火墙配置
├── setup_syncthing_mac.sh    # Mac 端 Syncthing 配置
├── setup_syncthing_win.ps1   # Windows 端 Syncthing 配置
├── sync_and_run.sh           # Mac 一键同步+运行指引
├── fetch_results.sh          # Mac 结果拉取指引
├── test_connection.py        # Mac 端连接测试
├── .stignore                 # Syncthing 忽略规则
├── .gitattributes            # Git LFS 配置
└── .gitignore                # Git 忽略规则
```

> **重要**：`mcp_run_experiment.m` 需要被 MATLAB 能找到。它应放在 `WinServerBuild` 目录或 Paper2 项目目录中，确保 MATLAB 工作目录的 addpath 能覆盖到。

### 4.2 安装 Python 依赖

```powershell
cd E:\code\WinServerBuild
pip install -r requirements.txt
```

### 4.3 修改配置

**优先修改 `.env` 文件**——这是所有配置的统一入口。Python 主服务启动时会自动加载它，`start_server.bat` 也会读取。

```ini
# .env 文件示例
MATLAB_WORKING_DIR=E:\code\Paper2
MCP_SERVER_DIR=E:\code\WinServerBuild
PYTHON_PATH=C:\Python310\python.exe

# 网络
MCP_HOST=0.0.0.0
MCP_PORT=8080

# Tailscale IP（Windows 端，Mac 连接用）
TAILSCALE_IP=100.x.y.z

# 认证（留空=不启用，强烈建议设置）
MCP_TOKEN=

# 日志目录
LOG_DIR=E:\code\WinServerBuild\logs

# 资源阈值
CPU_THRESHOLD=90
MEMORY_THRESHOLD=85
DISK_THRESHOLD=95
MAX_QUEUE_SIZE=5
MAX_RUNNING_TASKS=1
```

**配置优先级**（高 → 低）：
1. 系统环境变量（NSSM 的 `AppEnvironmentExtra` 等）
2. `.env` 文件
3. `config.py`
4. 代码内默认值

### 4.4 启动服务

**方式 1: 双击启动脚本**
```
双击 start_server.bat
```

**方式 2: 命令行启动**
```powershell
cd E:\code\WinServerBuild
python matlab_mcp_server.py
```

**方式 3: 安全启动器（推荐用于服务环境）**
```powershell
python cleanup_and_start.py
```
> `cleanup_and_start.py` 会先清理残留的 MATLAB Engine 进程（仅清理 `-automation` 模式的后台引擎，不影响用户打开的交互式 MATLAB），然后启动主服务。

**成功标志：**
```
MATLAB MCP Server 启动
  监听地址: http://0.0.0.0:8080/sse
  工作目录: E:\code\Paper2
MATLAB Engine 已启动，工作目录: E:\code\Paper2
```

---

## 五、网络配置（Tailscale）

### 为什么选择 Tailscale？

| 特性 | Tailscale | SSH 隧道 | 直接暴露端口 |
|------|-----------|----------|-------------|
| 设置难度 | 极低 | 中等 | 低 |
| 安全性 | 高 (WireGuard) | 高 | 低 |
| 需要公网 IP | 否 | 视情况 | 是 |
| 局域网/公网切换 | 自动 | 手动 | 不适用 |
| 需要开防火墙 | 否 | 否 | 是 |
| 费用 | 个人免费 | 免费 | 免费 |

### 5.1 安装 Tailscale

1. **Windows 端**: https://tailscale.com/download/windows
2. **Mac 端**: https://tailscale.com/download/mac (或 `brew install tailscale`)

### 5.2 登录同一账号

两端使用同一账号登录（支持 GitHub / Google / Microsoft 账号）。

### 5.3 验证连通性

```bash
# Mac 上查看 Windows 的 Tailscale IP
# 在 Tailscale 管理面板 (https://login.tailscale.com/admin/machines) 查看
# 或 Mac 终端:
/Applications/Tailscale.app/Contents/MacOS/Tailscale status

# 测试连通
ping 100.x.y.z  # 替换为 Windows 的 Tailscale IP
```

### 5.4 确定连接地址

- **局域网**: `http://192.168.1.100:8080/sse`（Windows 内网 IP）
- **公网 (Tailscale)**: `http://100.x.y.z:8080/sse`（Tailscale 分配的 IP）

> 使用 Tailscale 后，无论你在哪个网络，配置永远不用改。

---

## 六、防火墙配置

### 使用 Tailscale 时

**通常不需要配置防火墙**。Tailscale 走虚拟网卡，不经过 Windows 防火墙的入站规则。

### 局域网直连时

以管理员身份运行 PowerShell：

```powershell
# 方式 1: 运行配置脚本
.\setup_firewall.ps1

# 方式 2: 手动添加规则
New-NetFirewallRule -Name 'MATLAB-MCP' -DisplayName 'MATLAB MCP Server' `
    -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 8080
```

### 验证端口

```powershell
# 检查端口是否在监听
Get-NetTCPConnection -LocalPort 8080

# 从 Mac 测试
curl http://100.x.y.z:8080/sse
```

---

## 七、认证配置

服务支持可选的 Bearer Token 认证，防止未授权访问。**如果服务监听 `0.0.0.0` 且网络内有其他设备，强烈建议启用。**

### 7.1 设置 Token

在 `.env` 文件中设置：
```ini
MCP_TOKEN=your-secret-token-here
```

留空则不启用认证。

### 7.2 Mac 端连接方式

认证启用后，Mac 端 SSE URL 需附加 token 参数。支持两种方式：

**方式 1: Query parameter（推荐，兼容性最好）**
```json
{
  "mcpServers": {
    "matlab": {
      "type": "sse",
      "url": "http://100.x.y.z:8080/sse?token=your-secret-token-here"
    }
  }
}
```

**方式 2: Authorization header（需客户端支持自定义 header）**
```json
{
  "mcpServers": {
    "matlab": {
      "type": "sse",
      "url": "http://100.x.y.z:8080/sse",
      "headers": {
        "Authorization": "Bearer your-secret-token-here"
      }
    }
  }
}
```

> **提示**：多数 MCP 客户端（包括 Qoder）的 SSE 配置不支持自定义 header，推荐使用 query parameter 方式。

---

## 八、Mac 端客户端配置

### 8.1 Qoder / QoderWork 配置

在 MCP 设置中添加：

```json
{
  "mcpServers": {
    "matlab": {
      "type": "sse",
      "url": "http://100.x.y.z:8080/sse"
    }
  }
}
```

将 `100.x.y.z` 替换为 Windows 的 Tailscale IP（或局域网 IP）。

如果启用了认证，URL 改为 `http://100.x.y.z:8080/sse?token=your-token`。

### 8.2 测试连接

在 Mac 终端运行连接测试脚本：

```bash
cd /path/to/WinServerBuild
python3 test_connection.py http://100.x.y.z:8080/sse
```

脚本会依次测试 HTTP 连通性和 MCP 协议握手，并输出诊断信息。

### 8.3 验证工具可用

配置完成后，在 Qoder 中尝试：
- "获取 MATLAB 状态" → 应调用 `get_status` 工具
- "查看工作区变量" → 应调用 `get_workspace` 工具
- "健康检查" → 应调用 `health_check` 工具

---

## 九、开机自启动配置

### 方案 1: NSSM 注册为 Windows 服务（推荐）

1. 下载 NSSM: https://nssm.cc/download
2. 解压后将 `nssm.exe` 放入 `E:\code\WinServerBuild\`
3. 修改 `install_service.bat` 中的路径配置（或确保 `.env` 已正确配置）
4. 右键 → 以管理员身份运行 `install_service.bat`

> NSSM 实际调用的是 `cleanup_and_start.py`（而非直接调用 `matlab_mcp_server.py`），这样在服务崩溃重启时会自动清理残留的 MATLAB Engine 进程。

**管理命令：**
```powershell
nssm status MatlabMCPServer     # 查看状态
nssm restart MatlabMCPServer    # 重启
nssm stop MatlabMCPServer       # 停止
nssm remove MatlabMCPServer confirm  # 卸载
```

### 方案 2: Windows 任务计划程序

1. 打开"任务计划程序"
2. 创建基本任务 → 名称: "MATLAB MCP Server"
3. 触发器: "当用户登录时"
4. 操作: "启动程序"
   - 程序: `C:\Python310\python.exe`
   - 参数: `E:\code\WinServerBuild\cleanup_and_start.py`
   - 起始于: `E:\code\WinServerBuild`

### 方案 3: 启动文件夹快捷方式

1. 创建 `start_server.bat` 的快捷方式
2. 放入 `shell:startup` 文件夹（Win+R 输入 `shell:startup`）

---

## 十、Syncthing 代码同步

### 架构

```
Mac (~/Desktop/codes/Paper2/)  ◄══ Syncthing ══►  Windows (E:\code\Paper2\)
        代码双向同步 (paper2-code)
```

> **设计决策**: 实验结果 (.mat) 不同步回 Mac。
> 分析结果通过 MCP 工具远程完成（`execute_code` 加载 .mat、`get_variable` 查看数据、`save_figure` 导出图表）。
> 这样避免了大文件传输，且分析环境（MATLAB）就在 Windows 端。

### 快速配置

```bash
# Mac 端
chmod +x setup_syncthing_mac.sh
./setup_syncthing_mac.sh

# Windows 端 (PowerShell 管理员)
.\setup_syncthing_win.ps1
```

### 关键配置要点

1. 两台机器通过 **Tailscale IP** 连接: `tcp://100.x.y.z:22000`
2. 代码文件夹: **双向同步** + Staggered 版本控制 (7天)
3. 实验结果 (.mat) **不同步**，通过 MCP 远程分析
4. `.stignore` 排除 `.mat`、`results_*/`、`.asv`、`matlab_mcp_server.log` 等

### 验证同步

```bash
# 通过 MCP 工具检查
在 Qoder 中说: "检查文件同步状态"  → 调用 sync_status

# 或手动检查 Syncthing Web UI
open http://127.0.0.1:8384
```

---

## 十一、Git 版本控制工作流

### 初始化 (两端都要执行)

```bash
cd Paper2
git lfs install
git add .gitattributes
git add .gitignore
git commit -m "chore: add Git LFS config for .mat files"
```

### 日常流程

```bash
# Mac 端修改代码后
git add methods/alg_HeteroPSO_KR.m
git commit -m "创新点: 修改知识池查询策略"
git push

# Windows 端拉取
git pull
# (或者 Syncthing 已自动同步，Git 仅用于版本记录)
```

### 分支策略

```
master          ← 稳定版本
  └── dev       ← 日常开发
       └── exp/xxx  ← 实验分支（如 exp/knowledge-pool-v2）
```

### 注意事项

- `.mat` 文件走 Git LFS，两端都要 `git lfs install`
- 实验结果 (`results_*/`) 不走 Git，通过 Syncthing 同步
- Windows 端 `.bat`/`.ps1` 使用 CRLF，`.m`/`.py` 使用 LF

---

## 十二、功能接口说明

当前共 21 个工具（经三轮审查精简），按功能分类：

### 执行类

| 工具 | 功能 | 典型用途 |
|------|------|----------|
| `run` | 执行 MATLAB 代码（自动捕获图形，含耗时统计） | 快速计算、查询、绘图、中等实验 |
| `run_script` | 运行 .m 脚本或指定段落（section 参数） | 运行 Main.m 或只跑某个 section |
| `submit_task` | 提交异步后台任务 | 长时间实验（>30 分钟） |
| `experiment` | 运行封装实验（参数化 + raw_code 双模式） | 消融实验、对比实验、自定义实验 |

### 任务管理

| 工具 | 功能 |
|------|------|
| `get_task_status` | 查询后台任务状态 |
| `get_task_output` | 获取任务输出（运行中返回增量） |
| `cancel_task` | 取消后台任务 |
| `list_tasks` | 列出所有任务 |

### 工作区

| 工具 | 功能 |
|------|------|
| `inspect` | 查看工作区/变量值/struct 结构（mode 参数控制） |
| `set_variable` | 设置变量 |

### 图形与文件

| 工具 | 功能 |
|------|------|
| `save_figure` | 导出图形为 PNG (base64) |
| `get_figure_info` | 获取图形元数据（坐标轴/标签/图例） |
| `transfer_file` | 下载文件 (base64) |
| `upload_file` | 上传文件 |
| `list_files` | 列出目录文件 |

### 代码质量

| 工具 | 功能 |
|------|------|
| `lint_code` | MATLAB checkcode 静态检查（临时文件自动清理） |

### 监控与管理

| 工具 | 功能 |
|------|------|
| `diagnose` | 系统诊断（detail=quick 只看资源，detail=full 全链路） |
| `sync_status` | 检查 Syncthing 同步状态 |
| `reset_session` | 重置 MATLAB 工作区 |
| `change_directory` | 切换工作目录 |
| `force_restart_engine` | 强制重启 MATLAB Engine（清理卡死状态） |

### 工具选择指南

| 实验时长 | 推荐工具 | 说明 |
|----------|----------|------|
| < 10 分钟 | `run` | 快速计算、查询、绘图 |
| 10 - 30 分钟 | `run(timeout=1800)` | 单场景/多场景小批量 |
| > 30 分钟 | `submit_task` | 完整实验，后台运行 |
| 论文标准实验 | `experiment` | 调用 mcp_run_experiment.m，自动生成 manifest |

---

## 十三、使用示例

### 在 Qoder/QoderWork 中直接对话：

```
"在 MATLAB 中执行 x = linspace(0, 2*pi, 100); y = sin(x); plot(x, y)"

"运行实验，算法 HeteroPSO-KR，模型 1-10，重复 15 次，种子 42"

"查看当前工作区有哪些变量"

"获取变量 result.cost 的值"

"将当前图形导出为 PNG"

"列出 results_matlab 目录下的 .mat 文件"

"提交后台任务：跑全部 56 个模型"
```

### 典型实验工作流：

1. **检查环境**: "健康检查" → `health_check`
2. **运行实验**: "运行实验，算法 HeteroPSO-KR，模型 1-10，输出到 results_matlab/ablation_test" → `run_experiment`
3. **查看元数据**: "读取 results_matlab/ablation_test/manifest.json" → `execute_code`
4. **查看结果**: "列出 results_matlab/ablation_test 下的文件" → `list_files`
5. **分析数据**: "加载 model_1_result.mat 并显示 cost" → `execute_code`
6. **导出图形**: "绘制收敛曲线并导出为 PNG" → `save_figure`

### mcp_run_experiment.m 参数说明

`run_experiment` 工具内部调用 `mcp_run_experiment.m`，支持以下参数：

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `algo` | 是 | — | 算法名称（如 `HeteroPSO-KR`，自动映射到 `alg_HeteroPSO_KR` 函数） |
| `models` | 是 | — | 模型索引（如 `1:56` 或 `[1,3,5]`） |
| `output_dir` | 是 | — | 结果输出目录 |
| `n_runs` | 否 | 1 | 每个模型重复次数 |
| `seed` | 否 | 42 | 基础随机种子（实际种子 = seed×1000 + model_idx×10 + run_i） |
| `maxevals` | 否 | 15000 | 最大评估次数 |
| `particles` | 否 | 500 | 粒子数 |
| `extra_params` | 否 | — | 额外算法选项（struct） |

每次实验自动在 `output_dir` 下生成 `manifest.json`，记录算法、参数、种子、git commit、MATLAB 版本等，确保可复现。

---

## 十四、实验迭代操作流程

### 完整闭环

```
1. [Mac/Qoder] 修改代码 (alg_HeteroPSO_KR.m)
       ↓ Syncthing 自动同步 (~1秒)
2. [Windows] 代码已更新
       ↓
3. [Mac/Qoder] 通过 MCP 执行:
   - "检查同步状态"         → sync_status
   - "检查代码有没有问题"   → lint_code
   - "快速测试模型 1"       → run_and_wait
   - "提交后台实验 56 场景" → submit_task
       ↓
4. [Mac/Qoder] 跟踪进度:
   - "任务 T0001 跑完了吗"  → get_task_status
       ↓
5. [结果分析] 通过 MCP 远程完成（不同步 .mat 到 Mac）:
   - "读取 manifest.json"               → execute_code
   - "load results_matlab/xxx.mat; disp(cost)"  → execute_code
   - "绘制收敛曲线并导出 PNG"            → save_figure
       ↓
6. [Mac/Qoder] 对比分析:
   - "对比 results_matlab/A 和 B 的结果"
   - "绘制多组实验的收敛曲线对比图"
```

### 持久会话调试技巧

由于 MATLAB 会话是持久的，可以像交互式调试一样：

1. 先执行前置代码加载数据: `"load Model56.mat; model = Model{1};"`
2. 设置参数: `"opts.maxevals = 1000; opts.particles = 50;"`
3. 执行算法: `"[cost, sol] = alg_HeteroPSO_KR([], opts, model);"`
4. 检查结果: `"disp(cost); get_struct_info('sol')"`
5. 如果出错，变量仍在，可以继续调查

---

## 十五、故障排查与调试

### 服务无法启动

| 症状 | 原因 | 解决 |
|------|------|------|
| `ModuleNotFoundError: matlab.engine` | Engine API 未安装 | 重新执行 `python setup.py install` |
| `ModuleNotFoundError: mcp` | MCP SDK 未安装 | `pip install "mcp[cli]" uvicorn` |
| MATLAB Engine 启动超时 | MATLAB 未正确安装 | 确认 MATLAB 可正常打开 |
| 端口被占用 | 其他程序占用 8080 | 改端口或关闭占用程序 |
| 401 Unauthorized | 认证 token 不匹配 | 检查 `.env` 中 `MCP_TOKEN` 与客户端 URL 中 `?token=` 是否一致 |

### 连接问题

| 症状 | 原因 | 解决 |
|------|------|------|
| Mac 无法连接 | 防火墙阻止 | 运行 `setup_firewall.ps1` |
| Tailscale 不通 | Tailscale 未连接 | 检查系统托盘图标 |
| 连接超时 | 服务未启动 | 检查 Windows 端日志 |
| SSE 断开 | 网络不稳定 | Tailscale 会自动重连 |
| 工具调用卡住 | 后台任务持有引擎锁 | 等待后台任务完成，或用 `force_restart_engine` |

### MATLAB Engine 卡死

如果工具调用长时间无响应，可能是 MATLAB Engine 卡死：

1. 先尝试 `force_restart_engine` 工具（仅杀 `-automation` 模式的引擎进程）
2. 如果服务级别也卡住，重启 NSSM 服务：`nssm restart MatlabMCPServer`
3. 极端情况下手动清理：`taskkill /F /IM MATLAB.exe`（会杀所有 MATLAB，包括交互式）

### 调试流程

```
1. MCP 返回错误信息
   ↓
2. "检查这段代码" → lint_code 静态分析
   ↓
3. "执行到第 X 行停下来，显示变量" → execute_code 逐步执行
   ↓
4. "查看 result 变量的结构" → get_struct_info / get_variable
   ↓
5. [Mac] 修改代码 → Syncthing 同步 → 重新运行
```

### 常用调试命令 (在 Qoder 中直接说)

```
"在 MATLAB 中执行 dbstop if error"       ← 出错时自动暂停
"查看工作区变量"                        ← get_workspace
"获取 model 变量的字段结构"            ← get_struct_info('model')
"执行 try, alg_HeteroPSO_KR([], opts, model), catch ME, disp(ME), end"
```

### 查看日志

```powershell
# MCP 服务日志（路径取决于 .env 中的 LOG_DIR）
type E:\code\WinServerBuild\logs\matlab_mcp_server.log

# NSSM 服务日志
type E:\code\WinServerBuild\logs\service_stdout.log
type E:\code\WinServerBuild\logs\service_stderr.log

# MATLAB diary (如果开启了)
type E:\code\Paper2\diary.log
```

> 日志使用 `RotatingFileHandler`（10MB × 3 份），不会无限增长。

---

## 十六、后续扩展方案

### 已实现

- ✅ 异步执行 + 超时保护（`asyncio.wait_for`）
- ✅ 统一加锁（`matlab_eval` + `_engine_lock`，前台与后台不冲突）
- ✅ 自动图形捕获
- ✅ 段落执行 `execute_section`
- ✅ 代码质量检查 `lint_code`（临时文件自动清理）
- ✅ struct 元数据检查 `get_struct_info`
- ✅ 图形元数据 `get_figure_info`
- ✅ 后台任务队列 + 状态管理
- ✅ Bearer Token 认证（header + query parameter）
- ✅ 任务注册表自动清理
- ✅ 日志轮转（RotatingFileHandler）
- ✅ 实验元数据快照（`mcp_run_experiment.m` → `manifest.json`）
- ✅ 随机种子确定性管理
- ✅ MATLAB Engine 强制重启
- ✅ 精确进程清理（仅杀 `-automation` 引擎，不影响交互式 MATLAB）

### 待实现

- **文件传输增强**: 大文件分片传输、目录批量打包 (zip)
- **图形导出增强**: 批量导出、fig 格式保存、论文级图表模板
- **实验管理**: 断点续跑（记录已完成模型，中断后继续）、自动结果对比
- **操作审计**: 记录所有工具调用日志到独立审计文件
- **增量输出**: 后台任务运行中可读取 stdout 增量
- **工具精简**: 已从 28 个精简至 21 个（执行类 7→4、监控类 3→1、工作区 3→1）✓ 已完成

---

## 附录: 参考项目

| 项目 | 特点 | 借鉴内容 |
|------|------|----------|
| [matlab/matlab-mcp-server](https://github.com/matlab/matlab-mcp-server) | MathWorks 官方，Go 实现 | 工具设计思路 |
| [neuromechanist/matlab-mcp-tools](https://github.com/neuromechanist/matlab-mcp-tools) | 15 个工具，最完善 | section执行、struct检查、图形分析、lint |
| [jigarbhoye04/MatlabMCP](https://github.com/jigarbhoye04/MatlabMCP) | 异步执行、共享会话 | asyncio.to_thread 模式 |
| [Tsuchijo/matlab-mcp](https://github.com/Tsuchijo/matlab-mcp) | 自动图形捕获 | 执行后检测新图形 |
| [syncthing/syncthing](https://github.com/syncthing/syncthing) | P2P 实时文件同步 | 代码同步方案 |
