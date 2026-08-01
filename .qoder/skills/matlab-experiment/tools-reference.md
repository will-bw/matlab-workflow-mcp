# MATLAB MCP Server — Tool Reference

Complete parameter reference for all 21 MCP tools.

## Execution Tools

### run
Run MATLAB code in the persistent session. Auto-captures new figures.
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| code | str | (required) | MATLAB code (multi-line OK) |
| timeout | int | 0 | Timeout seconds (0 = default 600s, set 1800 for medium tasks) |
| description | str | "" | Experiment description (for logging) |

**Selection guide:**
- Quick verification (< 10min): call directly, timeout default
- Medium experiment (10-30min): set timeout=1800
- Long experiment (> 30min): use submit_task instead

### run_script
Run a .m script file.
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| script_path | str | (required) | Absolute or relative path to .m file |

## Background Task Tools

### submit_task
Submit a long-running task. Returns immediately with task_id.
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| code | str | (required) | MATLAB code to run in background |
| description | str | "" | Task description |

### get_task_status
Check task progress. Does NOT block.
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| task_id | str | "" | Task ID (e.g. "T0001"). Empty = list all |

### get_task_output
Get completed task output.
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| task_id | str | (required) | Task ID |
| tail_lines | int | 100 | Show last N lines (0 = all) |

### cancel_task
Cancel a running task.
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| task_id | str | (required) | Task ID to cancel |

### list_tasks
List all background tasks and their statuses. No parameters.

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
Download a file from Windows (returns base64). ⚠️ Only for small files.
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
Unified diagnostic entry.
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| detail | str | "full" | "quick" (resources + queue only) / "full" (MATLAB + Syncthing + Tailscale) |

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
