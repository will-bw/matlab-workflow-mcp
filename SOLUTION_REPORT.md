# 跨平台 MATLAB 远程实验系统 — 方案讲解报告

> 项目代号: WinServerBuild
> 适用场景: Mac 端通过 AI IDE (Qoder) 远程驱动 Windows 端 MATLAB 执行 UAV 路径规划实验
> 日期: 2026-07-28 (更新)

---

## 一、问题背景

### 1.1 现状痛点

Paper2 项目（UAV 动态 4D 路径规划）的实验代码运行在 Windows + MATLAB R2022b 环境上，而日常开发和分析工作在 Mac 上进行。这导致：

- **环境割裂**: 代码在 Mac 上编辑，却必须到 Windows 上手动运行
- **迭代低效**: 改一行代码 → 切到 Windows → 打开 MATLAB → 运行 → 看结果 → 切回 Mac，一次迭代 5-10 分钟
- **长实验失控**: 56 场景 × 15 次重复的实验需要数小时，期间无法做其他事
- **结果分析断裂**: .mat 结果文件在 Windows 上，Mac 端无法直接分析

### 1.2 设计目标

构建一个**端到端的远程实验系统**，实现：

1. 在 Mac 上用自然语言驱动 Windows 上的 MATLAB
2. 代码修改后 1 秒内自动同步到 Windows
3. 数小时的实验可以后台运行、随时查看进度
4. 实验结果在 Windows 端通过 MATLAB 远程分析，无需传输大文件
5. 完整的版本控制和错误调试支持

---

## 二、系统架构

### 2.1 总体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Tailscale 虚拟网络                              │
│                    (WireGuard 加密, 100.x.y.z 网段)                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Mac (开发端)                        Windows (计算端)                    │
│  ┌───────────────────┐              ┌───────────────────────────────┐   │
│  │  Qoder IDE        │              │  matlab_mcp_server.py         │   │
│  │  ├─ AI Agent      │   SSE/HTTP   │  ├─ FastMCP (27 个工具)       │   │
│  │  ├─ MCP Client    │─────────────►│  ├─ MATLAB Engine (持久会话)  │   │
│  │  ├─ Skills 指导   │   :8080      │  ├─ 后台任务管理器            │   │
│  │  └─ 代码编辑器    │              │  └─ 负载监控 + 资源预警       │   │
│  │                   │              │                               │   │
│  │  Syncthing        │   P2P Sync   │  Syncthing                    │   │
│  │  (Paper2 代码)    │◄────────────►│  (Paper2 代码)                │   │
│  │                   │   :22000      │                               │   │
│  │  Git (版本管理)   │              │  MATLAB R2022b                │   │
│  └───────────────────┘              │  ├─ Paper2 项目               │   │
│                                     │  ├─ Model56.mat (56个场景)    │   │
│                                     │  └─ results_matlab/ (实验结果)│   │
│                                     └───────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 三层通信设计

| 层级 | 协议 | 用途 | 特点 |
|------|------|------|------|
| 执行层 | MCP over SSE (:8080) | AI 调用 MATLAB 工具 | 请求-响应，支持异步 |
| 同步层 | Syncthing P2P (:22000) | 代码文件实时同步 | 双向、增量、加密 |
| 网络层 | Tailscale (WireGuard) | 底层网络互通 | 局域网/公网自动切换 |

### 2.3 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| MCP 传输协议 | SSE (非 STDIO) | 支持远程连接，STDIO 只能本地 |
| 网络方案 | Tailscale (非 SSH 隧道) | 无需公网 IP，自动打洞，永久在线 |
| 文件同步 | Syncthing (非 rsync/Git) | 实时、双向、无需手动触发 |
| 结果分析 | MCP 远程 (非同步回 Mac) | .mat 文件大，MATLAB 分析能力在 Windows |
| 长实验 | 后台任务队列 (非同步等待) | 数小时实验不能阻塞 SSE 连接 |
| MATLAB 接口 | Engine API (非 -batch) | 持久会话，变量不丢失 |
| 资源保护 | 阈值预检 + 队列限制 | 防止持续提交导致服务器崩溃 |
| AI 指导 | Qoder Skills (非纯文档) | AI 自动识别意图并选择正确工具 |

---

## 三、MCP Server 核心设计

### 3.1 技术选型

```python
# 核心依赖
matlab.engine          # MATLAB Engine API for Python (R2022b 兼容)
mcp.server.fastmcp    # Python MCP SDK, FastMCP 框架
```

选择 Python 而非官方 Go 实现的原因：
- MATLAB Engine API 只有 Python 绑定，Go 版本通过命令行调用 MATLAB（无持久会话）
- Python 可以实现真正的持久会话（变量不丢失）
- 开发效率高，核心逻辑约 1879 行

### 3.2 持久会话机制

```python
eng = None  # 全局单例

def get_engine():
    global eng
    if eng is None:
        eng = matlab.engine.start_matlab()  # 启动一次，永久保持
        eng.cd(MATLAB_WORKING_DIR)
    return eng
```

**效果**: 所有 21 个工具共享同一个 MATLAB 进程。用户先 `load Model56.mat`，后续所有操作都能直接使用 `Model` 变量，无需重复加载。

### 3.3 工具分类（21 个，经三轮审查精简）

```
┌─────────────────────────────────────────────────────────────┐
│  执行 (3)                                                     │
│  run / run_script / submit_task                              │
├─────────────────────────────────────────────────────────────┤
│  实验 (1)                                                     │
│  experiment (参数化 + raw_code 双模式)                       │
├─────────────────────────────────────────────────────────────┤
│  任务管理 (4)                                                  │
│  get_task_status / get_task_output / cancel_task / list_tasks│
├─────────────────────────────────────────────────────────────┤
│  工作区 (2)                                                    │
│  inspect (auto/value/structure) / set_variable              │
├─────────────────────────────────────────────────────────────┤
│  图形与文件 (5)                                                │
│  save_figure / get_figure_info / transfer_file /             │
│  upload_file / list_files                                    │
├─────────────────────────────────────────────────────────────┤
│  代码质量 (1)                                                  │
│  lint_code                                                   │
├─────────────────────────────────────────────────────────────┤
│  监控与管理 (5)                                                │
│  diagnose / sync_status / force_restart_engine /             │
│  reset_session / change_directory                            │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 后台任务队列（解决长实验问题）

**问题**: 56 场景 × 15 次重复 = 数小时。SSE 连接不能保持这么久。

**解决方案**:

```python
class BackgroundTask:
    task_id: str          # T0001, T0002...
    status: str           # pending → running → completed/failed
    output: str           # 完成后的全部输出
    start_time/end_time   # 耗时统计

# 提交时: 创建 daemon 线程，立即返回 task_id
thread = threading.Thread(target=_run_background_task, daemon=True)
thread.start()
return "Task ID: T0001"  # 不阻塞

# 查询时: 直接读内存中的状态，无需等 MATLAB
def get_task_status(task_id):
    return task.status, task.elapsed
```

**工具选择指南**:

| 实验时长 | 工具 | 阻塞? |
|----------|------|-------|
| < 10 分钟 | `run` | 是（可接受） |
| 10 - 30分钟 | `run(timeout=1800)` | 是（带超时保护） |
| > 30 分钟 | `submit_task` | 否（后台运行） |

### 3.5 线程安全设计

MATLAB Engine API **不支持并发调用**。设计约束：

```python
_engine_lock = threading.Lock()           # 互斥锁
_executor = ThreadPoolExecutor(max_workers=1)  # 单线程池

# 所有 MATLAB 调用都通过单线程池串行执行
# 后台任务持有锁期间，快速查询会排队等待
```

这意味着：当后台实验在跑时，`get_workspace` 等快速查询需要等待。这是 MATLAB Engine 的固有限制，但 `get_task_status` 和 `list_tasks` 不需要 MATLAB 调用，可以立即响应。

### 3.6 AI 工具发现机制

MCP 协议内置了工具自动发现：

```
Qoder 连接 SSE → 发送 tools/list → 服务端返回 21 个工具的:
  - 名称 (run)
  - 描述 (docstring 第一行)
  - 参数 schema (code: str, timeout: int)
```

AI 根据 docstring 判断调用哪个工具。因此每个工具的 docstring 都精心设计了"适合什么场景"的说明。

此外，项目提供了 **Qoder Skills** (`.qoder/skills/matlab-experiment/`)，包含：
- 工具选择决策树（按实验时长、操作类型自动分流）
- 5 个核心工作流模板（快速执行、长实验、结果分析、调试、预检）
- 21 个工具的完整参数手册

### 3.7 负载监控与任务调度控制

**问题**: 持续提交任务可能导致 Windows 服务器 CPU/内存耗尽而崩溃。

**解决方案**: 三层保护机制：

```python
# 1. 资源预检 — 提交前自动检查
CPU_THRESHOLD = 90%      # CPU 超过则拒绝
MEMORY_THRESHOLD = 85%   # 内存超过则拒绝
DISK_THRESHOLD = 95%     # 磁盘超过则拒绝

# 2. 队列限制 — 防止无限堆积
MAX_QUEUE_SIZE = 5       # 最多排队 5 个任务
MAX_RUNNING_TASKS = 1    # MATLAB 单线程，同时只跑 1 个

# 3. 强制覆盖 — 紧急情况
submit_task(code, force=True)  # 跳过所有检查
```

**`server_load` 工具输出示例**:
```
[服务器资源监控]
  CPU:    ✓ ████░░░░░░░░░░░░░░░░ 23.5% (阈值 90%)
  内存:   ✓ ████████████░░░░░░░░ 62.1% (阈值 85%)
          可用 12.3 GB / 总计 32.0 GB
  磁盘:   ✓ ██████████████░░░░░░ 71.2% (阈值 95%)

  [任务队列]
    运行中: 1/1  |  排队中: 0/5

  [结论] ✓ 服务器状态良好，可以接受新任务
```

资源监控兼容有无 `psutil`：未安装时自动回退到 Windows `wmic` 命令。

---

## 四、文件同步方案

### 4.1 为什么选 Syncthing

| 方案 | 实时性 | 方向 | 是否需要服务器 | 适合 |
|------|--------|------|----------------|------|
| **Syncthing** | 实时 (~1s) | 双向 | 否 (P2P) | 开发代码同步 |
| rsync | 手动 | 单向 | 需 SSH | 部署/备份 |
| Git push/pull | 手动 | 双向 | 需远程仓库 | 版本管理 |
| MCP upload_file | 按需 | 双向 | 需 MCP | 单文件传输 |

Syncthing 的核心优势：
- **无感同步**: 保存文件后 1 秒内到达对端，无需任何手动操作
- **走 Tailscale**: 已有网络基础设施，无需额外配置
- **增量传输**: 只传修改的部分，高效
- **版本历史**: 内置 Staggered Versioning，可回滚 7 天

### 4.2 同步策略

```
同步什么:  *.m, *.py, *.json, *.txt (代码和配置)
不同步:    *.mat (太大), results_*/ (通过 MCP 远程分析), *.asv (临时)
方向:      双向 (Mac 改代码 → Windows, Windows 改代码 → Mac)
```

`.stignore` 文件控制排除规则，确保只同步有意义的代码文件。

### 4.3 结果分析策略

**核心决策**: .mat 结果文件不同步回 Mac。

理由：
1. 单个 .mat 结果文件 1-50MB，56 个场景 × 多组实验 = 数 GB
2. 分析 .mat 需要 MATLAB 环境（Mac 上没有）
3. MCP 已提供完整的远程分析能力：
   - `execute_code("load xxx.mat; disp(cost)")` — 加载并查看
   - `get_struct_info("result")` — 查看结构
   - `save_figure("plot(history.costs)")` — 绘图并导出 PNG
   - `transfer_file("xxx.mat")` — 确实需要时按需下载

---

## 五、版本控制方案

### 5.1 Git + Git LFS 策略

```
普通 Git 跟踪:  *.m, *.py, *.sh, *.bat, *.ps1, *.md
Git LFS 跟踪:   *.mat (Model56.mat ~50MB), *.png, *.fig
Git 忽略:       results_*/, *.asv, __pycache__/, .stfolder
```

### 5.2 跨平台换行符处理

`.gitattributes` 确保：
- `.m` / `.py` / `.sh` → LF (Unix)
- `.bat` / `.ps1` → CRLF (Windows)

避免 Mac 编辑后 Windows 运行报语法错误。

### 5.3 分支策略

```
master ← 论文提交版本
  └── dev ← 日常开发
       └── exp/knowledge-pool-v2 ← 实验分支
```

Syncthing 负责实时同步（快速迭代），Git 负责版本记录（里程碑管理）。两者互补，不冲突。

---

## 六、实验迭代完整流程

### 6.1 日常迭代（改代码 → 验证）

```
[Mac/Qoder] 修改 alg_HeteroPSO_KR.m 中的知识池查询策略
     │
     │  Syncthing 自动同步 (~1秒)
     ▼
[Windows] 代码已更新（无需任何操作）
     │
     │  在 Qoder 中说: "检查代码有没有问题"
     ▼
[MCP] lint_code → 返回静态分析结果
     │
     │  "快速测试模型 1，只看能不能跑通"
     ▼
[MCP] execute_code → 10秒内返回 cost 值
     │
     │  确认没问题，提交完整实验
     ▼
[Mac/Qoder] "提交后台任务，跑全部 56 个场景"
     │
     │  立即返回: Task ID: T0001
     ▼
（去做其他事...）
     │
     │  2小时后: "T0001 跑完了吗？"
     ▼
[MCP] get_task_status → ✅ completed, 耗时 2h 15m
     │
     │  "加载结果，对比 baseline 和 full 的 cost"
     ▼
[MCP] execute_code → 在 MATLAB 中加载 .mat 并分析
     │
     │  "画收敛曲线对比图，导出 PNG"
     ▼
[MCP] save_figure → 返回 base64 图片，直接在 Qoder 中显示
```

### 6.2 错误调试流程

```
[MCP] execute_code 返回: "MATLAB 错误: 索引超出矩阵维度"
     │
     │  "查看 model 变量的结构"
     ▼
[MCP] get_struct_info("model") → 显示字段列表和大小
     │
     │  发现 model.n 没设置
     ▼
[Mac] 修改代码，添加 model.n = 5
     │
     │  Syncthing 同步
     ▼
[MCP] execute_code → 重新运行，成功
```

关键优势：**持久会话**使得调试像交互式 MATLAB 一样自然。变量一直在，可以逐步排查。

---

## 七、网络与安全

### 7.1 Tailscale 组网

```
Mac (100.x.y.1) ◄──── WireGuard 加密隧道 ────► Windows (100.x.y.2)
     │                                              │
     │  同一局域网时: 自动走直连 (低延迟)            │
     │  不同网络时: 自动打洞或走中继 (DERP)          │
     │                                              │
     └── 无论在哪，IP 永远不变，配置永远不用改 ──────┘
```

### 7.2 安全考量

| 层面 | 措施 |
|------|------|
| 传输加密 | Tailscale (WireGuard) + Syncthing (TLS) |
| 端口暴露 | MCP 端口 8080 仅对 Tailscale 网段可达 |
| 防火墙 | Windows 防火墙可选限制来源 IP |
| 认证 | Bearer Token（设置 MCP_TOKEN 环境变量启用） |

### 7.3 高可用

- MCP Server 通过 NSSM 注册为 Windows 服务，崩溃自动重启
- `cleanup_and_start.py` 安全启动器：重启前自动清理残留 MATLAB 进程，防止内存泄漏
- Syncthing 开机自启，断线自动重连
- Tailscale 开机自启，网络切换无感
- 负载监控：资源超阈值时自动拒绝新任务，保护服务器不崩溃

---

## 八、参考项目与借鉴

| 项目 | Stars | 借鉴内容 |
|------|-------|----------|
| [matlab/matlab-mcp-server](https://github.com/matlab/matlab-mcp-server) | 1.2k | 官方工具设计思路、参数规范 |
| [neuromechanist/matlab-mcp-tools](https://github.com/neuromechanist/matlab-mcp-tools) | — | section 执行、struct 检查、图形分析、lint（最完善） |
| [jigarbhoye04/MatlabMCP](https://github.com/jigarbhoye04/MatlabMCP) | — | asyncio.to_thread 异步模式、线程安全 |
| [Tsuchijo/matlab-mcp](https://github.com/Tsuchijo/matlab-mcp) | — | 自动图形捕获、脚本管理 |
| [syncthing/syncthing](https://github.com/syncthing/syncthing) | 65k+ | P2P 文件同步基础设施 |

---

## 九、交付物清单

```
WinServerBuild/
├── matlab_mcp_server.py      # 核心服务 (1832 行, 27 个 MCP 工具)
├── DEPLOYMENT_GUIDE.md       # 部署操作手册 (16 章)
├── SOLUTION_REPORT.md        # 方案讲解报告 (本文档)
├── config.py                 # 配置参考
├── requirements.txt          # Python 依赖 (含 psutil)
│
├── cleanup_and_start.py      # 安全启动器 (进程清理)
├── start_server.bat          # Windows 快速启动
├── install_service.bat       # NSSM 服务安装 (开机自启)
├── setup_firewall.ps1        # Windows 防火墙配置
│
├── setup_syncthing_mac.sh    # Mac Syncthing 安装配置
├── setup_syncthing_win.ps1   # Windows Syncthing 安装配置
├── .stignore                 # Syncthing 忽略规则
│
├── sync_and_run.sh           # Mac 一键同步+运行
├── fetch_results.sh          # Mac 结果拉取 (按需)
├── test_connection.py        # 连接测试工具
│
├── .qoder/skills/matlab-experiment/
│   ├── SKILL.md              # Qoder AI Skill (工具选择指导)
│   └── tools-reference.md    # 27 个工具参数手册
│
├── .gitattributes            # Git LFS 配置
└── .gitignore                # Git 忽略规则
```

---

## 十、总结

本方案通过 **MCP Server + Syncthing + Tailscale + Git + Qoder Skills** 五层架构，将原本割裂的 Mac 开发 / Windows 实验流程整合为一个无缝的端到端工作流：

- **改代码**: Mac 上编辑，1 秒自动同步
- **跑实验**: 自然语言驱动，后台运行不阻塞
- **看结果**: MCP 远程分析，无需传输大文件
- **管版本**: Git LFS 管理代码和数据
- **修 Bug**: 持久会话 + 交互式调试
- **防崩溃**: 负载监控 + 队列限制 + 资源预警
- **AI 指导**: Qoder Skills 自动选择正确工具

整个系统个人使用完全免费（Tailscale 免费 3 台设备，Syncthing 开源），且一旦配置完成，日常使用零运维。
