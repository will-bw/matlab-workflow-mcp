---
name: matlab-experiment
description: Drive remote MATLAB experiments on Windows via MCP Server tools. Use when the user wants to run MATLAB code, execute experiments, check task progress, analyze results, export figures, debug MATLAB errors, or manage the remote MATLAB session. Triggers on mentions of MATLAB, experiment, run code, submit task, check results, plot figure, or workspace variables.
---

# MATLAB Remote Experiment Skill

You have access to a remote MATLAB MCP Server (26 tools) running on Windows via SSE.
The MATLAB session is **persistent** — variables survive between calls.

## Tool Selection Decision Tree

```
User wants to...
├─ Run quick code (< 10s)          → execute_code
├─ Run a .m script file            → run_script
├─ Run a section of a script       → execute_section
├─ Run medium experiment (5-30min) → run_and_wait
├─ Run long experiment (> 30min)   → submit_task → get_task_status → get_task_output
├─ Check what's in workspace       → get_workspace
├─ See a variable's value          → get_variable
├─ Inspect struct fields           → get_struct_info
├─ Set a variable                  → set_variable
├─ Export a plot as image          → save_figure
├─ Get plot metadata               → get_figure_info
├─ Download a file from Windows    → transfer_file
├─ Upload a file to Windows        → upload_file
├─ List remote files               → list_files
├─ Check code quality              → lint_code
├─ Check system health             → health_check
├─ Check sync status               → sync_status
├─ Reset MATLAB workspace          → reset_session
└─ Diagnose problems               → health_check (first), then get_status
```

## Core Workflows

### 1. Quick Code Execution

```
execute_code(code="x = linspace(0,2*pi,100); y = sin(x); plot(x,y)")
```
- Variables persist: subsequent calls can use `x` and `y`
- New figures are auto-detected and reported

### 2. Long Experiment Lifecycle

```
Step 1: submit_task(code="RunAblationChunk(1,1,'output_base','results/test')", description="Ablation group 1")
        → Returns task_id (e.g. "T0001")

Step 2: get_task_status(task_id="T0001")
        → Shows: running/completed/failed + elapsed time

Step 3: get_task_output(task_id="T0001", tail_lines=50)
        → Shows final output after completion
```

**Rules:**
- Experiments > 30 min: ALWAYS use submit_task (never execute_code)
- Experiments 5-30 min: use run_and_wait(timeout=1800)
- Experiments < 5 min: execute_code is fine

### 3. Result Analysis (remote, no file sync needed)

```
Step 1: execute_code(code="load('results_matlab/test/model_1_result.mat')")
Step 2: get_struct_info(var_name="result")        → see fields
Step 3: get_variable(var_name="result.cost")       → get specific value
Step 4: save_figure(figure_code="plot(result.history.costs)")  → export plot
```

### 4. Debugging MATLAB Errors

```
Step 1: Read the error message from execute_code output
Step 2: lint_code(file_path="methods/alg_HeteroPSO_KR.m")  → static analysis
Step 3: execute_code(code="whos")                           → check workspace state
Step 4: get_variable(var_name="model")                      → inspect data
Step 5: Fix code locally → Syncthing auto-syncs → re-run
```

### 5. Pre-Flight Check (before running experiments)

```
Step 1: health_check()     → all components OK?
Step 2: sync_status()      → code synced to Windows?
Step 3: execute_code(code="pwd; ver")  → MATLAB responsive?
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

1. **Never run > 30min experiments with execute_code** — use submit_task
2. **Always check sync_status before running modified code** — avoid stale code
3. **Results stay on Windows** — analyze via execute_code + save_figure, don't transfer .mat files
4. **Session is persistent** — no need to re-load data between calls
5. **On any error, run health_check first** — diagnose before retrying
6. **For batch experiments, prefer run_experiment or submit_task** over manual loops

## Additional Resources

- For complete tool parameter reference, see [tools-reference.md](tools-reference.md)
