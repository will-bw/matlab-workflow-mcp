# MATLAB MCP Server — Tool Reference

Complete parameter reference for all 22 MCP tools.

Transport: Streamable HTTP (default, endpoint `/mcp`) | SSE (legacy, endpoint `/sse`)

## Execution Tools

### run
Run MATLAB code in the persistent session. Auto-captures new figures.
Heartbeat every 30s keeps connection alive during long execution.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| code | str | (required) | MATLAB code (multi-line OK) |
| timeout | int | 0 | Timeout seconds (0 = default 600s, set 1800 for medium tasks) |
| description | str | "" | Experiment description (for logging) |

**Selection guide:**
- Quick verification (< 10min): call directly, timeout default
- Medium experiment (10-30min): set timeout=1800
- Long experiment (> 30min): use submit_task instead

**Error responses:**
- `[ENGINE_BUSY]` — 引擎被后台任务占用（等 15s 超时），等待或取消后台任务
- `[TIMEOUT]` — 超过 timeout 秒，改用 submit_task
- `[MATLAB_ERROR]` — MATLAB 运行时错误，附带详细错误信息

### run_script
Run a .m script file, or execute a specific section.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| script_path | str | (required) | Absolute or relative path to .m file |
| section | str | "" | Section: "" = run all, "1" = by index, "Title" = by match, "list" = list sections |

## Background Task Tools

### submit_task
Submit a long-running task. Returns immediately with task_id.
Pre-submission checks: system resources + queue capacity.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| code | str | (required) | MATLAB code to run in background |
| description | str | "" | Task description |
| force | bool | False | Skip resource checks (emergency only) |

**Behavior:**
- 引擎被占用超过 60s → 任务自动标记 `failed`（不会静默卡死）
- 运行期间 stdout 实时可读（LiveOutput）

### get_task_status
Check task progress. Does NOT block. Does NOT occupy engine.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| task_id | str | "" | Task ID (e.g. "T0001"). Empty = list all |

**Returns:**
- status: pending / running / completed / failed / cancelled
- elapsed: 实际执行耗时（不含排队）
- wait_time: 排队等待耗时
- last_activity: 最后一次有输出的时间（running 时显示）
- JSON block for programmatic parsing

### get_task_output
Get task output. **Running tasks show real-time output (LiveOutput).**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| task_id | str | (required) | Task ID |
| tail_lines | int | 100 | Show last N lines (0 = all) |

**Behavior change (v2.0):**
- 运行中: 返回已有输出 + 耗时 + 最后活动时间
- 完成后: 返回完整输出

### cancel_task
Cancel a running task. Note: if MATLAB eval is in progress, cancellation takes effect after current eval completes.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| task_id | str | (required) | Task ID to cancel |

### list_tasks
List all background tasks and their statuses. No parameters.

### get_history (NEW)
View recent execution history (audit log). Records all run/submit_task calls.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| n | int | 20 | Show last N records (max 100) |

**Returns:** time, tool, code summary, elapsed, success/failure for each entry.

## Workspace Tools

### inspect
Unified workspace/variable inspection.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| var_name | str | "" | Variable name (empty = list workspace, non-empty = show variable) |
| max_elements | int | 1000 | Max elements to display |
| max_depth | int | 2 | Struct recursion depth (only for mode=structure) |
| mode | str | "auto" | "auto" / "value" / "structure" |

**Usage examples:**
- List all workspace variables: `inspect()`
- Show variable value: `inspect(var_name="result")` or `inspect(var_name="Model{1}")`
- Show struct tree: `inspect(var_name="result", mode="structure")`

### set_variable
Set a workspace variable via MATLAB expression.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| var_name | str | (required) | Variable name |
| value | str | (required) | MATLAB expression, e.g. "[1,2,3]", "rand(5)" |

## Experiment Tools

### experiment
Run paper experiments (unified entry).

**Two modes:**
1. Parameterized: specify algo/models/n_runs/seed → calls mcp_run_experiment.m
2. Raw code: pass raw_code (full MATLAB experiment code) → executes directly

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| algo | str | "HeteroPSO-KR" | Algorithm name |
| models | str | "1:56" | Model range (e.g. "1:10", "[1,5,10]") |
| n_runs | int | 1 | Runs per model |
| output_base | str | "" | Output directory (auto-timestamped if empty) |
| extra_params | str | "" | Extra params: "n=10, maxevals=30000, particles=1000" |
| seed | int | 42 | Random seed for reproducibility |
| raw_code | str | "" | Raw MATLAB code (overrides all other params) |

**Selection guide:**
- Standard paper experiment → parameterized mode
- Custom/complex experiment → raw_code mode
- Experiment > 30 min → use submit_task instead

## Figure & File Tools

### save_figure
Export a MATLAB figure as image (returns base64). ⛔ 禁止使用——太慢。

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| figure_code | str | "" | Code to generate figure (empty = export current) |
| fig_handle | str | "gcf" | Figure handle expression |
| filename | str | "" | Output filename (auto if empty) |
| format | str | "png" | Format: png, jpg, svg, pdf |
| dpi | int | 150 | Resolution |

**⛔ 不要调用此工具。** 出图统一用：
```
run(code="exportgraphics(gcf, 'exports/fig.png', 'Resolution', 200)")
```
然后从 Mac 本地读取 `~/Desktop/codes/Paper2/exports/fig.png`（Syncthing 同步）。

### get_figure_info
Get figure metadata (axes, labels, legends, line data).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| fig_handle | str | "gcf" | Figure handle expression |

### transfer_file
Download a file from Windows (returns base64). ⚠️ Only for small files (< 50MB).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| file_path | str | (required) | File path (absolute or relative) |
| encoding | str | "base64" | Encoding method |

### upload_file
Upload a file to Windows.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| file_path | str | (required) | Target path on Windows |
| base64_data | str | (required) | Base64-encoded file content |

### list_files
List files in a remote directory.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| directory | str | "." | Directory path |
| pattern | str | "*" | Glob pattern (e.g. "*.mat") |

## Code Quality

### lint_code
Run MATLAB checkcode static analysis.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| code | str | "" | Code to check (or use file_path) |
| file_path | str | "" | File to check (or use code) |
| severity | str | "all" | Filter: "all", "warning", "error" |

## System Management

### diagnose
Unified diagnostic entry. Shows resources, task queue, engine status.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| detail | str | "full" | "quick" (resources + queue only) / "full" (MATLAB + Syncthing + Tailscale) |

**v2.0 behavior:** Engine 忙时显示 "引擎忙（后台任务占用中）" 而非阻塞。

### sync_status
Check Syncthing file sync status. No parameters.

### force_restart_engine
Force restart MATLAB Engine. ⚠️ Loses all workspace variables.
Use when engine is stuck (e.g. timeout but MATLAB still running). No parameters.

### reset_session
Clear MATLAB workspace.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| clear_all | bool | False | Also close figures and clear history |

### change_directory
Change MATLAB working directory.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| path | str | (required) | Target directory path |

## Health Endpoint (HTTP, not MCP tool)

`GET /health` — 无需认证，供外部监控探活：
```json
{
  "status": "ok",
  "engine_busy": false,
  "tasks_running": 0,
  "tasks_pending": 0,
  "uptime_seconds": 3600,
  "transport": "streamable-http",
  "version": "2.0"
}
```
