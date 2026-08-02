# MATLAB MCP Server v3.0 — Tool Reference

17 tools. Architecture: matlab -batch subprocess pool (up to 3 concurrent).

> **Concurrency note**: `run` and `submit_task` share the same 3-slot process pool. When 3 background tasks are running, any `run` call will **queue and wait** until a slot frees up (or timeout). Plan analysis/inspection calls around batch execution windows.

## Execution Tools

### run
Execute MATLAB code in an independent process. Waits for completion.
**Code must be self-contained** (load data, addpath, etc. within the call).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| code | str | (required) | Self-contained MATLAB code |
| timeout | int | 0 | Timeout seconds (0 = default 600s) |
| description | str | "" | Description for logging |

**Use when**: Quick execution < 10 min, debugging, one-off checks.

> **Timeout semantics**: After the specified timeout (default 600s), the server grants a 60s grace period then **hard-kills** the MATLAB process. Unsaved in-memory results are lost.
>
> **Inline code limitation**: Code is wrapped in `try...catch...end` internally. MATLAB does not allow `function` definitions inside try blocks. If your code needs local functions, write it as a `.m` file and use `run_script` or `upload_file` + `run_script`.

### run_script
Run a .m script file on the remote server.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| script_path | str | (required) | Path to .m file |
| section | str | "" | "" = all, "1" = by index, "list" = list sections |

**Use when**: Running existing scripts (< 10 min) already on the remote server.

> **Fixed timeout**: 600s (not configurable). Long scripts will be killed. For scripts > 10 min, use `submit_task` with the script content instead.

### experiment
Run paper experiments (parameterized or raw code). Submits as background task.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| algo | str | "HeteroPSO-KR" | Algorithm name |
| models | str | "1:56" | Model range |
| n_runs | int | 1 | Runs per model |
| output_base | str | "" | Output directory |
| extra_params | str | "" | "n=10, maxevals=30000" |
| seed | int | 42 | Random seed |
| raw_code | str | "" | Raw MATLAB code (overrides all) |

**Use when**: Standard benchmark experiments with known structure.

> **Prerequisites**: Parameterized mode (without `raw_code`) requires `mcp_run_experiment.m` to exist in the remote MATLAB working directory. This file is project-specific and must be deployed (e.g., via Syncthing sync) before use. If absent, only `raw_code` mode works.
>
> **Project-specific defaults**: The default `algo="HeteroPSO-KR"` and `models="1:56"` are Paper2-specific. For other projects, always specify these explicitly or use `raw_code`.

## Task Management

### submit_task
Submit background task. Returns immediately. **Supports true parallel execution.**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| code | str | (required) | Self-contained MATLAB code |
| description | str | "" | Task description |
| timeout | int | 0 | Timeout (0 = 3600s for background) |

**Use when**: Long experiments > 10 min, parallel batch execution.

### get_task_status
Check task status. Does NOT occupy a MATLAB slot.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| task_id | str | "" | Task ID. Empty = list all |

### get_task_output
Get task output. **Real-time readable while running.**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| task_id | str | (required) | Task ID |
| tail_lines | int | 100 | Last N lines (0 = all) |

### cancel_task
Cancel task (kills process if running, removes if queued).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| task_id | str | (required) | Task ID |

### list_tasks
List all tasks (running + queued + recent history). No parameters.

### get_history
View execution audit log.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| n | int | 20 | Last N records (max 100) |

## Inspection

### inspect
Check .mat file contents (variables, sizes, types).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| file_path | str | (required) | Path to .mat file |

**Use when**: Verify result structure before loading, check file integrity.

> **Fixed timeout**: 120s. Very large .mat files with thousands of variables may hit this limit.

## Figure & File Tools

### save_figure
Execute plotting code and save to exports/ (Syncthing syncs to local).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| figure_code | str | (required) | MATLAB plotting code |
| filename | str | "" | Output name (auto if empty) |
| format | str | "png" | png/svg/pdf |
| dpi | int | 200 | Resolution |

**Use when**: All figure generation. Figures sync automatically via Syncthing.

> **Fixed timeout**: 300s. Complex multi-panel figures with heavy data may need `run` + manual `exportgraphics` instead.

### list_files
List remote directory contents.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| directory | str | "." | Directory path |
| pattern | str | "*" | Glob pattern |

### transfer_file
Download file from Windows (base64). Limit 50MB.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| file_path | str | (required) | File path |

**Use when**: Downloading small result files (.mat summaries, .json). Never for images.

### upload_file
Upload file to Windows.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| file_path | str | (required) | Target path |
| base64_data | str | (required) | Base64 content |

## Code Quality

### lint_code
MATLAB checkcode static analysis.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| code | str | "" | Code to check |
| file_path | str | "" | File to check |

**Use when**: Validate code before long submissions. Catches syntax errors early.

> **Fixed timeout**: 120s.

## System

### diagnose
Server diagnostics (resources, scheduler, components).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| detail | str | "full" | "quick" or "full" |

**Use when**: Pre-flight check before experiments. Shows CPU, memory, working dir.

### sync_status
Check Syncthing file sync status. No parameters.

**Use when**: Before running modified code, before expecting figure sync.

> **Limitation**: Only reports Syncthing device connection status. "Device connected" ≠ "your specific file has synced". For critical code changes, verify at file level (see SKILL.md § Sync Verification).

## Tool Selection for Experiment Phases

| Phase | Primary Tools | Supporting Tools |
|-------|--------------|------------------|
| DESIGN | — | — (local planning) |
| PREPARE | lint_code | diagnose, sync_status, list_files |
| EXECUTE | submit_task, run | get_task_status, get_task_output |
| ANALYZE | run, inspect | list_files, transfer_file |
| REPORT | save_figure | sync_status |

## Removed Tools (v2.0 → v3.0)

These tools were removed because persistent workspace no longer exists:
- `set_variable` — use self-contained code instead
- `reset_session` — no session to reset
- `force_restart_engine` — no engine
- `change_directory` — use run("cd('...')")

## Health Endpoint

`GET /health` (no auth required):
```json
{
  "status": "ok",
  "version": "3.0",
  "transport": "streamable-http",
  "tasks_running": 1,
  "tasks_queued": 0,
  "max_concurrent": 3,
  "cpu_percent": 45.2,
  "memory_percent": 62.1
}
```
