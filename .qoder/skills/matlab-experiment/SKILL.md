---
name: matlab-experiment
description: Drive remote MATLAB experiments on Windows via MCP Server tools. Use when the user wants to run MATLAB code, execute experiments, check task progress, analyze results, export figures, debug MATLAB errors, or manage the remote MATLAB session. Triggers on mentions of MATLAB, experiment, run code, submit task, check results, plot figure, or workspace variables.
---

# MATLAB Remote Experiment Skill

You have access to a remote MATLAB MCP Server (22 tools) running on Windows.
Transport: **Streamable HTTP** (MCP 2025-03-26, endpoint `/mcp`) with SSE fallback.
The MATLAB session is **persistent** — variables survive between calls.

## Architecture Constraints

- **Single MATLAB Engine**: 同一时刻只能执行一个 MATLAB 命令（单线程锁）
- **Engine 忙时行为**: 后台任务占用引擎时，前台命令等待 15s 后返回 `[ENGINE_BUSY]` 错误（不会崩溃）
- **后台任务启动**: 如果引擎被占用超过 60s，任务自动标记为 `failed`
- **心跳保活**: `run` 工具每 30s 发送心跳，长时间执行不会断开连接

## Tool Selection Decision Tree

```
User wants to...
├─ Run quick code (< 10s)          → run
├─ Run a .m script file            → run_script
├─ Run medium experiment (5-30min) → run (with timeout=1800)
├─ Run long experiment (> 30min)   → submit_task → get_task_status → get_task_output
├─ Check what's in workspace       → inspect
├─ Set a variable                  → set_variable
├─ Export figure(s) to view        → ★ See Figure Export Strategy (must check sync first)
├─ Get plot metadata               → get_figure_info
├─ Download a file from Windows    → transfer_file (small files only)
├─ Upload a file to Windows        → upload_file
├─ List remote files               → list_files
├─ Check code quality              → lint_code
├─ Check system health             → diagnose
├─ Check sync status               → sync_status
├─ View execution history          → get_history
├─ Reset MATLAB workspace          → reset_session
└─ Diagnose problems               → diagnose
```

## Error Handling Guide

所有错误返回结构化格式 `[ERROR_TYPE] message`：

| 错误类型 | 含义 | 处理方式 |
|---------|------|---------|
| `ENGINE_BUSY` | 后台任务占用引擎 | 等待任务完成，或用 get_task_status 监控 |
| `TIMEOUT` | 执行超时 | 改用 submit_task 提交后台任务 |
| `MATLAB_ERROR` | MATLAB 运行时错误 | 检查代码逻辑，用 lint_code 分析 |
| `PYTHON_ERROR` | 服务器内部错误 | 运行 diagnose 检查状态 |

**遇到 ENGINE_BUSY 时：**
```
1. get_task_status() → 查看哪个后台任务在跑
2. 等待其完成，或 cancel_task(task_id) 取消
3. 重试前台命令
```

## Figure Export Strategy (IMPORTANT)

**所有图形导出统一走 Syncthing 文件同步，不走 base64。**

### Step 0: 检查 Syncthing 状态

```
sync_status()  → 如果返回 "Syncthing 不可用"，停止出图流程，提示用户：
               "Syncthing 同步未连接，无法导出图片。请先在 Windows 端启动 Syncthing。"
```

### 出图流程（Syncthing 在线时）

Figures saved to `exports/` on Windows auto-sync to Mac via Syncthing.

**Paths:**
- Windows (MATLAB): `E:\code\Paper2\exports\`
- Mac (local read): `~/Desktop/codes/Paper2/exports/`

**Step-by-step:**
```
Step 1: run(code="... plotting code ...; exportgraphics(gcf, 'exports/my_figure.png', 'Resolution', 200)")
        → MATLAB saves figure to synced exports/ folder

Step 2: Wait 2-3 seconds for Syncthing to sync

Step 3: Read the local file: ~/Desktop/codes/Paper2/exports/my_figure.png
        → Display to user with markdown image syntax
```

**Batch figures example:**
```matlab
% In run(code=...)
for i = 1:10
    figure; plot(data{i});
    exportgraphics(gcf, sprintf('exports/fig_%02d.png', i), 'Resolution', 200);
    close(gcf);
end
```
Then read all 10 figures locally — zero MCP transfer overhead.

### 禁止事项

- **永远不要用 `save_figure` 工具传图**（base64 太慢，体验极差）
- **永远不要用 `transfer_file` 传图片文件**
- Syncthing 断开时，告知用户而非尝试其他传输方式

## Core Workflows

### 1. Quick Code Execution

```
run(code="x = linspace(0,2*pi,100); y = sin(x); plot(x,y)")
```
- Variables persist: subsequent calls can use `x` and `y`
- New figures are auto-detected and reported

### 2. Long Experiment Lifecycle

```
Step 1: submit_task(code="RunAblationChunk(1,1,'output_base','results/test')", description="Ablation group 1")
        → Returns task_id (e.g. "T0001")

Step 2: get_task_status(task_id="T0001")
        → Shows: status + elapsed + wait_time + last_activity

Step 3: get_task_output(task_id="T0001", tail_lines=50)
        → 运行中: 实时显示已有输出（LiveOutput）
        → 完成后: 显示最终结果
```

**Rules:**
- Experiments > 30 min: ALWAYS use submit_task (never run)
- Experiments 5-30 min: use run(timeout=1800)
- Experiments < 5 min: run is fine
- **后台任务运行期间不要执行前台 run**（会返回 ENGINE_BUSY）
- 用 get_task_status / get_task_output 监控进度（这两个不占引擎）

### 3. Result Analysis (remote, no file sync needed)

```
Step 1: run(code="load('results_matlab/test/model_1_result.mat')")
Step 2: inspect(var_name="result")        → see fields
Step 3: run(code="disp(result.cost)")     → get specific value
Step 4: run(code="plot(result.history.costs); exportgraphics(gcf, 'exports/cost_history.png', 'Resolution', 200)")
        → Then read local: ~/Desktop/codes/Paper2/exports/cost_history.png
```

### 4. Debugging MATLAB Errors

```
Step 1: Read the error message (structured: [MATLAB_ERROR] details)
Step 2: lint_code(file_path="methods/alg_HeteroPSO_KR.m")  → static analysis
Step 3: run(code="whos")                                   → check workspace state
Step 4: inspect(var_name="model")                          → inspect data
Step 5: Fix code locally → Syncthing auto-syncs → re-run
```

### 5. Pre-Flight Check (before running experiments)

```
Step 1: diagnose()     → all components OK?
Step 2: sync_status()  → code synced to Windows?
Step 3: run(code="pwd; ver")  → MATLAB responsive?
```

### 6. Review Execution History

```
get_history(n=20)  → 查看最近 20 次 run/submit_task 的记录
                   → 包含时间、代码摘要、耗时、成功/失败
```

## Paper2 Project Context

The MATLAB workspace is `E:\code\Paper2` (UAV 4D path planning).

Key files:
- `methods/alg_HeteroPSO_KR.m` — main algorithm (2017 lines)
- `RunAblationChunk.m` — ablation experiment runner
- `RunExperiments.m` — batch experiment framework
- `ExperimentConfigs.m` — experiment configuration presets
- `Model56.mat` — 56 terrain+threat scenarios

Key patterns:
```matlab
% Load scenarios
load('Model56.mat');  % creates Model cell array (56 elements)
model = Model{1};     % get one scenario
model.n = 5;          % set waypoint count

% Run algorithm
opts = struct('maxevals', 15000, 'particles', 500, 'subpops', 3, 'rrt_enabled', true);
[cost, sol, history] = alg_HeteroPSO_KR([], opts, model);

% Ablation experiment (long-running)
RunAblationChunk(group_idx, run_idx, 'output_base', 'results_matlab/ablation_v2')
```

## Important Rules

1. **Never run > 30min experiments with run** — use submit_task
2. **Always check sync_status before running modified code** — avoid stale code
3. **Results stay on Windows** — analyze via run + inspect, don't transfer .mat files
4. **Figures: 必须先检查 sync_status** — 在线则存 `exports/` 读本地；断开则提示用户启动 Syncthing，不用 base64
5. **Session is persistent** — no need to re-load data between calls
6. **On ENGINE_BUSY, check get_task_status** — 不要反复重试前台命令
7. **For batch experiments, prefer experiment or submit_task** over manual loops
8. **永远不用 save_figure 或 transfer_file 传图** — 只走 Syncthing 同步 + 本地读取
9. **后台任务运行期间只用 get_task_status/get_task_output** — 不要用 run/inspect 等前台工具

## Additional Resources

- For complete tool parameter reference, see [tools-reference.md](tools-reference.md)
