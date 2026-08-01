# MATLAB MCP Server v3.0 — Tool Reference

18 tools. Architecture: matlab -batch subprocess pool (up to 3 concurrent).

## Execution Tools

### run
Execute MATLAB code in an independent process. Waits for completion.
**Code must be self-contained** (load data, addpath, etc. within the call).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| code | str | (required) | Self-contained MATLAB code |
| timeout | int | 0 | Timeout seconds (0 = default 600s) |
| description | str | "" | Description for logging |

### run_script
Run a .m script file.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| script_path | str | (required) | Path to .m file |
| section | str | "" | "" = all, "1" = by index, "list" = list sections |

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

## Task Management

### submit_task
Submit background task. Returns immediately. **Supports true parallel execution.**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| code | str | (required) | Self-contained MATLAB code |
| description | str | "" | Task description |
| timeout | int | 0 | Timeout (0 = 3600s for background) |

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

## Figure & File Tools

### save_figure
Execute plotting code and save to exports/ (Syncthing syncs to Mac).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| figure_code | str | (required) | MATLAB plotting code |
| filename | str | "" | Output name (auto if empty) |
| format | str | "png" | png/svg/pdf |
| dpi | int | 200 | Resolution |

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

## System

### diagnose
Server diagnostics (resources, scheduler, components).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| detail | str | "full" | "quick" or "full" |

### sync_status
Check Syncthing file sync status. No parameters.

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
