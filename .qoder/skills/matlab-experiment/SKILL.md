---
name: matlab-experiment
description: Drive remote MATLAB experiments on Windows via MCP Server tools. Use when the user wants to run MATLAB code, execute experiments, check task progress, analyze results, export figures, debug MATLAB errors, or manage the remote MATLAB session. Triggers on mentions of MATLAB, experiment, run code, submit task, check results, plot figure, or workspace variables.
---

# MATLAB Remote Experiment Skill (v3.0)

Remote MATLAB MCP Server (18 tools) on Windows.
Architecture: **matlab -batch subprocess pool** — true parallel execution (up to 3 concurrent).
Transport: Streamable HTTP (endpoint `/mcp`).

## Key Architecture Differences (v3.0)

- **No persistent workspace**: Each `run` call is an independent MATLAB process. Variables do NOT survive between calls.
- **Self-contained code**: Every call must `load` its own data, `addpath` its own paths.
- **True parallelism**: Up to 3 MATLAB processes run simultaneously.
- **Smart scheduling**: Tasks auto-queue when resources are insufficient.
- **Cold start**: Each execution has ~10-30s MATLAB startup overhead.

## Tool Selection Decision Tree

```
User wants to...
├─ Run code (< 10min)              → run (self-contained code!)
├─ Run a .m script file            → run_script
├─ Run long experiment (> 10min)   → submit_task → get_task_status → get_task_output
├─ Run paper experiment            → experiment
├─ Check .mat file contents        → inspect(file_path)
├─ Export figure                   → save_figure (or run + exportgraphics)
├─ Download a file from Windows    → transfer_file
├─ Upload a file to Windows        → upload_file
├─ List remote files               → list_files
├─ Check code quality              → lint_code
├─ Check system health             → diagnose
├─ Check sync status               → sync_status
├─ View execution history          → get_history
└─ Monitor/cancel tasks            → get_task_status / cancel_task / list_tasks
```

## Critical: Self-Contained Code Pattern

```matlab
% WRONG (v2.0 style, won't work):
run("load('Model56.mat')")
run("model = Model{1}")       ← ERROR: Model doesn't exist in this process!

% CORRECT (v3.0 style):
run("load('Model56.mat'); model = Model{1}; disp(model.n)")
```

Every `run` call must include ALL necessary context:
```matlab
run("addpath('methods'); load('Model56.mat'); model = Model{1}; [cost,sol] = alg_HeteroPSO_KR([], opts, model); disp(cost)")
```

## Figure Export Strategy

**All figures via Syncthing sync, never base64.**

```
Step 1: sync_status() → confirm Syncthing online
Step 2: run("... plot code ...; exportgraphics(gcf, 'exports/fig.png', 'Resolution', 200)")
Step 3: Wait 2-3s → Read local: ~/Desktop/codes/Paper2/exports/fig.png
```

Or use `save_figure(figure_code="...", filename="my_fig")` which does this automatically.

**Never use transfer_file for images.** Syncthing offline → tell user, don't try alternatives.

## Core Workflows

### 1. Quick Execution
```
run(code="addpath('methods'); load('Model56.mat'); disp(numel(Model))")
```

### 2. Long Experiment (parallel!)
```
submit_task(code="addpath('methods'); RunAblationChunk(1,1,'output_base','results/v3')", timeout=7200)
submit_task(code="addpath('methods'); RunAblationChunk(2,1,'output_base','results/v3')", timeout=7200)
→ Both run SIMULTANEOUSLY (different MATLAB processes)

get_task_status("T0001")  → monitor
get_task_output("T0001")  → real-time output
```

### 3. Check Results
```
inspect(file_path="results/v3/model_1_result.mat")  → see variables
run("load('results/v3/model_1_result.mat'); disp(cost)")  → get value
```

### 4. Pre-Flight Check
```
diagnose()     → resources + scheduler status
sync_status()  → code synced?
```

## Error Handling

| Error Type | Meaning | Action |
|-----------|---------|--------|
| `QUEUE_FULL` | Task queue full (10 max) | Wait for tasks to finish |
| `TIMEOUT` | Execution exceeded timeout | Increase timeout or use submit_task |
| `MATLAB_ERROR` | MATLAB runtime error | Check code, use lint_code |
| `FILE_NOT_FOUND` | File doesn't exist | Check path, verify sync |

## Important Rules

1. **Code must be self-contained** — no variable sharing between calls
2. **Always addpath in your code** — each process starts fresh
3. **Long experiments: use submit_task** — supports parallel execution
4. **Figures: Syncthing only** — never base64
5. **Check sync_status before running modified code**
6. **Multiple submit_task calls run in parallel** — up to 3 concurrent
7. **Cold start ~10-30s is normal** — don't panic if first output is delayed

## Paper2 Project Context

Workspace: `E:\code\Paper2` (UAV 4D path planning).

Standard code template:
```matlab
addpath(fullfile(pwd, 'methods'));
addpath(fullfile(pwd, 'aux_files'));
addpath(fullfile(pwd, 'utils'));
load('Model56.mat');
model = Model{1};
opts = struct('maxevals', 15000, 'particles', 500);
[cost, sol, history] = alg_HeteroPSO_KR([], opts, model);
```

## Additional Resources

- Tool reference: [tools-reference.md](tools-reference.md)
