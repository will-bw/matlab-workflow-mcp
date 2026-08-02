---
name: matlab-experiment
description: Drive remote MATLAB experiments on Windows via MCP Server tools with full academic experiment management. Use when the user wants to run MATLAB code, execute experiments, check task progress, analyze results, export figures, debug MATLAB errors, manage experiment metadata, generate experiment reports, or organize experiment files. Triggers on mentions of MATLAB, experiment, run code, submit task, check results, plot figure, ablation, comparison, parameter sweep, experiment log, workspace variables, 跑实验, 消融实验, 出图, 远程MATLAB, 提交任务, 查看结果, 参数扫描, 对比实验.
---

# MATLAB Experiment Management Skill

Professional experiment management for academic paper writing, powered by remote MATLAB MCP Server. Architecture: **matlab -batch subprocess pool** (up to 3 concurrent). Transport: Streamable HTTP (endpoint `/mcp`).

## Core Architecture Principles

- **No persistent workspace**: Each `run` call is an independent MATLAB process. Variables do NOT survive between calls.
- **Self-contained code**: Every call must `load` its own data and `addpath` its own paths.
- **True parallelism**: Up to 3 MATLAB processes run simultaneously. `run` and `submit_task` **share** the same 3-slot pool.
- **Smart scheduling**: Tasks auto-queue when resources are insufficient (max 5 queued + 3 running = 8 total).
- **Workspace sandbox**: All file-based tools (run_script, inspect, lint_code, list_files, transfer_file, upload_file, save_figure) are restricted to the configured `MATLAB_WORKING_DIR`. Accessing paths outside this directory raises PermissionError.
- **Cold start**: Each execution has ~10-30s MATLAB startup overhead.
- **Full traceability**: Every experiment is logged with code, purpose, parameters, and results.

## Intent Recognition & Decision Tree

```
User wants to...
├─ Run code (< 10min)              → run (self-contained, NO function defs!)
├─ Run a .m script file (< 10min)  → run_script (fixed 600s timeout)
├─ Run long experiment (> 10min)   → submit_task → get_task_status → get_task_output
├─ Run structured paper experiment → experiment (requires mcp_run_experiment.m!) or [Lifecycle Workflow]
├─ Design experiment plan          → [Experiment Design Workflow]
├─ Check experiment progress       → get_task_status / list_tasks
├─ Analyze results                 → [Analysis Workflow] (wait for batch to finish first!)
├─ Compare experiments             → [Comparison Workflow]
├─ Generate report                 → [Reporting Workflow]
├─ Check .mat file contents        → inspect
├─ Export figure                   → save_figure (or run + exportgraphics)
├─ Download a file from Windows    → transfer_file
├─ Upload a file to Windows        → upload_file
├─ List remote files               → list_files
├─ Check code quality              → lint_code
├─ Check system health             → diagnose
├─ Check sync status               → sync_status (+ file-level verify!)
├─ View execution history          → get_history
└─ Monitor/cancel tasks            → get_task_status / cancel_task / list_tasks
```

## Critical: Self-Contained Code Pattern

Because there is no persistent workspace, every `run`/`submit_task` call must carry ALL its context.

```matlab
% WRONG — variables don't survive between calls:
run("load('data.mat')")
run("x = loaded_var + 1")       ← ERROR: loaded_var doesn't exist here

% CORRECT — do everything in one call:
run("load('data.mat'); x = loaded_var + 1; disp(x)")
```

Always include `addpath(...)` for any non-default directories, using `pwd`-relative paths:
```matlab
run("addpath(fullfile(pwd, 'methods')); load('data.mat'); ...")
```

**Inline code cannot contain `function` definitions.** The server wraps code in `try...catch...end`, and MATLAB forbids function definitions inside try blocks. If your code needs local functions:
1. Write it as a `.m` file, sync to remote, then use `run_script`
2. Or use `upload_file` to push the .m file, then `run_script`

## Discovering Paths (Never Hardcode)

**Do not assume any fixed path.** Discover the environment dynamically:

1. `diagnose()` → shows server resources and working directory context.
2. `list_files(directory=".")` → see what's in the remote workspace root.
3. `run("pwd")` / `run("dir")` → confirm the MATLAB working directory.
4. `sync_status()` → confirm which local directory is synced with the remote.

If a path is unclear, **ask the user** rather than guessing.

**Workspace sandbox constraint**: All file-based tools are confined to `MATLAB_WORKING_DIR` (configured in server's config.py). Attempts to access paths outside this directory will fail with PermissionError. Use `diagnose()` to discover the working directory boundary.

## Sync Verification (Critical)

`sync_status()` only reports Syncthing **device connection** — it does NOT confirm that your specific file has arrived. After modifying code locally, always do a **file-level content check** before execution:

```matlab
% Embed a version marker in your modified file, then verify remotely:
run("c = fileread('methods/alg_MyAlgorithm.m'); if contains(c, 'VERSION_20260802'), disp('SYNCED'); else, disp('NOT SYNCED'); end")
```

If NOT SYNCED, wait a few seconds and retry. Do not proceed with stale code.

## Experiment Lifecycle Overview

Every experiment follows a 5-phase lifecycle. See [experiment-lifecycle.md](references/experiment-lifecycle.md) for details.

```
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│  DESIGN │───▶│ PREPARE │───▶│ EXECUTE │───▶│ ANALYZE │───▶│  REPORT │
└─────────┘    └─────────┘    └─────────┘    └─────────┘    └─────────┘
  Define         Validate       Submit &       Collect &      Generate
  hypothesis     code &         monitor        compute        structured
  & params       pre-flight                    statistics     report
```

### Phase 1: DESIGN
- Clarify experiment purpose and hypothesis
- Define parameters, variables, and expected outcomes
- Choose experiment type (ablation / comparison / sensitivity / validation)
- Create experiment plan with metadata

### Phase 2: PREPARE
- Write self-contained MATLAB code
- Run `lint_code` to verify syntax
- Run `diagnose()` + `sync_status()` for pre-flight check
- Estimate runtime and resource needs

### Phase 3: EXECUTE
- Submit via `submit_task` (long) or `run` (short)
- Monitor with `get_task_status` / `get_task_output`
- Log execution metadata (timestamp, task_id, duration)

### Phase 4: ANALYZE
- Collect results via `inspect` / `run("load(...)")`
- Compute statistics (mean, std, MRE, ranks)
- Run significance tests if comparing groups
- Generate visualizations via `save_figure`

### Phase 5: REPORT
- Generate structured experiment report (Markdown)
- Save to local experiment log directory
- Update experiment index for future retrieval

## Local Experiment Log System

All experiment metadata is stored locally in the user's project. See [directory-structure.md](references/directory-structure.md) for the full specification.

**Root directory**: `<project_root>/experiment_log/`

```
experiment_log/
├── index.json                     # Master experiment index
├── YYYY-MM-DD_<experiment-id>/    # One folder per experiment
│   ├── metadata.json              # Structured metadata
│   ├── code/                      # Executed MATLAB code
│   │   └── main.m
│   ├── results/                   # Synced/downloaded results
│   ├── figures/                   # Generated figures
│   └── report.md                  # Analysis report
└── ...
```

**When creating an experiment log entry, always:**
1. Generate a descriptive experiment ID: `YYYY-MM-DD_<short-name>`
2. Save the complete executed code (not a summary)
3. Record the hypothesis, parameters, and expected outcomes
4. After completion, attach results summary and analysis

## Core Workflows

### Workflow A: Quick Execution (No Logging)
```
run(code="<self-contained MATLAB code>")
```
For exploratory runs, debugging, or one-off checks. No formal logging needed.

### Workflow B: Logged Experiment

```
1. Create experiment folder + metadata.json
2. Save code to code/main.m
3. Pre-flight: diagnose() + sync_status()
4. Execute: submit_task(code=..., timeout=...)
5. Monitor: get_task_status(task_id)
6. Collect: inspect / run("load(...)")
7. Analyze: compute statistics
8. Report: generate report.md
9. Update: index.json
```

### Workflow C: Batch Experiment (Ablation / Comparison / Sweep)

```
1. Define experiment matrix (groups × parameters)
2. Create parent folder + experiment_plan.json
3. For each group:
   a. Generate self-contained code
   b. submit_task (parallel up to 3!)
   c. Monitor all tasks
4. After all complete:
   a. Collect all results
   b. Cross-group statistical analysis
   c. Generate comparison report with tables
5. Update index.json
```

### Workflow D: Result Analysis

```
1. Locate results: list_files / inspect
2. Load and aggregate: run("load(...); ...")
3. Compute metrics: mean, std, MRE, Friedman ranks, Wilcoxon
4. Visualize: save_figure (Syncthing sync)
5. Document: write analysis to report.md
```

## Figure Export Strategy

**All figures via Syncthing sync, never base64.**

```
Step 1: sync_status()        → confirm Syncthing device connected
Step 2: run("... plot code ...; exportgraphics(gcf, 'exports/fig.png', 'Resolution', 200)")
Step 3: Verify local file    → check the synced copy exists (retry up to 10s; sync delay is 2-10s)
```

Or use `save_figure(figure_code="...", filename="my_fig")` which handles export + sync automatically.

**Never use transfer_file for images.** If Syncthing is offline, tell the user — don't silently fall back.

## Error Handling

| Error Type | Meaning | Action |
|-----------|---------|--------|
| `QUEUE_FULL` | Task queue full (max 5 queued + 3 running) | Wait for tasks to finish, then retry |
| `TIMEOUT` | Execution exceeded timeout (+ 60s grace then hard-kill) | Increase timeout, add incremental save, or chunk work |
| `MATLAB_ERROR` | MATLAB runtime error (includes stack trace) | Check error message + stack, use lint_code |
| `FILE_NOT_FOUND` | File doesn't exist in workspace | Check path, verify sync at file level |
| `PATH_TRANSLATION` | Path outside workspace sandbox | Use only paths within MATLAB_WORKING_DIR |
| `INVALID_SECTION` | run_script section index out of range | Use section="list" to see available sections |
| `FILE_TOO_LARGE` | transfer_file exceeds 50MB limit | Use Syncthing or chunk the data |

> **Note**: Some tools (transfer_file, upload_file) return unstructured `[错误] ...` text rather than coded errors. Read the message content for diagnosis.

## Important Rules

1. **Code must be self-contained** — no variable sharing between calls.
2. **Always addpath in your code** — each process starts fresh; prefer `pwd`-relative paths.
3. **Long experiments: use submit_task** — supports parallel execution.
4. **Figures: Syncthing only** — never base64.
5. **Verify sync at file level** — `sync_status()` only checks device connection; use `fileread` + marker string to confirm your specific file arrived.
6. **Multiple submit_task calls run in parallel** — up to 3 concurrent; `run` also occupies a slot, so avoid `run` during batch execution.
7. **Cold start ~10-30s is normal** — don't panic if first output is delayed.
8. **Never hardcode paths** — discover via diagnose/list_files/pwd, or ask the user.
9. **Always log formal experiments** — save code + metadata + results locally.
10. **Use structured naming** — experiment IDs follow `YYYY-MM-DD_<name>` convention.
11. **No function defs in inline code** — use .m file + run_script for code with local functions.
12. **Incremental save for long tasks** — save each result immediately; timeout = hard-kill with no recovery.

## Additional Resources

- Experiment lifecycle: [experiment-lifecycle.md](references/experiment-lifecycle.md)
- Metadata schema: [metadata-schema.md](references/metadata-schema.md)
- Directory structure: [directory-structure.md](references/directory-structure.md)
- Analysis & reporting: [analysis-reporting.md](references/analysis-reporting.md)
- Tool reference: [tools-reference.md](tools-reference.md)
