# MATLAB MCP Server — Tool Reference

Complete parameter reference for all 26 MCP tools.

## Execution Tools

### execute_code
Run MATLAB code in the persistent session. Auto-captures new figures.
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| code | str | (required) | MATLAB code (multi-line OK) |
| timeout | int | 0 | Timeout seconds (0 = use EXEC_TIMEOUT=600) |

### run_script
Run a .m script file.
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| script_path | str | (required) | Absolute or relative path to .m file |

### execute_section
Run a specific section (%% delimited) of a script.
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| file_path | str | (required) | Path to .m file |
| section | str | "0" | Index ("0","1"), title match, "all", or "list" |

### run_and_wait
Run code and block until done. For 5-30 min experiments.
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| code | str | (required) | MATLAB code |
| timeout | int | 1800 | Max wait seconds (30 min) |
| description | str | "" | Label for logging |

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

### get_workspace
List all workspace variables (like `whos`). No parameters.

### get_variable
Display a variable's value (truncated for large arrays).
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| var_name | str | (required) | Variable name, e.g. "result.cost", "Model{1}" |
| max_elements | int | 1000 | Max elements to display |

### get_struct_info
Show struct/cell metadata (fields, types, sizes) without data.
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| var_name | str | (required) | Variable name |
| max_depth | int | 2 | Recursion depth |

### set_variable
Set a workspace variable via MATLAB expression.
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| var_name | str | (required) | Variable name |
| value | str | (required) | MATLAB expression, e.g. "[1,2,3]", "rand(5)" |

## Experiment Tools

### run_experiment
Run a packaged experiment (ablation or custom).
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| experiment_type | str | (required) | "ablation_chunk" or "custom" |
| algo | str | "HeteroPSO-KR" | Algorithm name |
| models | str | "1:56" | Model range |
| n_runs | int | 1 | Number of runs |
| output_base | str | "" | Output directory (auto if empty) |
| extra_params | str | "" | Extra params: "n=10, maxevals=30000" |

### run_batch_experiment
Run arbitrary MATLAB experiment configuration code.
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| config_code | str | (required) | Full MATLAB experiment code |
| description | str | "" | Description for logging |

## Figure & File Tools

### save_figure
Export a MATLAB figure as image (returns base64).
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| figure_code | str | "" | Code to generate figure (empty = export current) |
| fig_handle | str | "gcf" | Figure handle expression |
| filename | str | "" | Output filename (auto if empty) |
| format | str | "png" | Format: png, jpg, svg, pdf |
| dpi | int | 150 | Resolution |

### get_figure_info
Get figure metadata (axes, labels, legends, line data).
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| fig_handle | str | "gcf" | Figure handle expression |

### transfer_file
Download a file from Windows (returns base64).
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

### health_check
One-shot diagnostic of all components. No parameters.
Checks: MATLAB Engine, working dir, Syncthing, Tailscale, background tasks.

### sync_status
Check Syncthing file sync status. No parameters.

### get_status
Get MATLAB session info (version, memory, uptime). No parameters.

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
