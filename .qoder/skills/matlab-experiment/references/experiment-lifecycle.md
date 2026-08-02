# Experiment Lifecycle Management

## Overview

Every formal experiment follows a 5-phase lifecycle. This document details each phase's actions, decision points, and quality gates.

## Phase 1: DESIGN

### Objective
Transform a research question into a concrete, executable experiment plan.

### Actions

1. **Clarify the hypothesis**
   - What specific claim does this experiment validate?
   - What is the expected outcome (quantitative if possible)?
   - What would constitute success vs. failure?

2. **Classify experiment type**

   | Type | Purpose | Typical Structure |
   |------|---------|-------------------|
   | Ablation | Isolate contribution of each component | Baseline + incremental additions |
   | Comparison | Benchmark against existing methods | Same conditions, different algorithms |
   | Sensitivity | Test robustness to parameter changes | Parameter sweep over ranges |
   | Validation | Confirm correctness of implementation | Known-answer tests, edge cases |
   | Scalability | Test performance at different scales | Varying problem dimensions |

3. **Define experiment matrix**
   - Independent variables (what you change)
   - Dependent variables (what you measure)
   - Control variables (what you keep fixed)
   - Number of independent runs (≥15 for statistical significance)

4. **Estimate resources**
   - Runtime per single execution
   - Total executions = groups × scenarios × runs
   - Total time estimate → decide parallelization strategy
   - Memory requirements per MATLAB process (~1GB each)

### Quality Gate
Before proceeding, confirm:
- [ ] Hypothesis is falsifiable
- [ ] Variables are clearly defined
- [ ] At least one baseline/control group exists
- [ ] Resource estimate fits within available time

## Phase 2: PREPARE

### Objective
Write correct, self-contained MATLAB code and verify the execution environment.

### Actions

1. **Write self-contained code**
   ```matlab
   % Template: every execution must include these elements
   addpath(fullfile(pwd, 'methods'));
   addpath(fullfile(pwd, 'aux_files'));
   addpath(fullfile(pwd, 'utils'));
   
   % Load required data
   load('<data_file>.mat');
   
   % Configure parameters (inline, not from workspace)
   param1 = <value>;
   param2 = <value>;
   
   % === CRITICAL: Time window self-termination ===
   % Prevents hard-kill by timeout; reserves time for final save
   TIME_LIMIT = <timeout_seconds> - 120;  % 2min safety margin
   t0 = tic;
   
   % === CRITICAL: Incremental save + skip-completed ===
   % Each result is saved immediately; on restart, skip existing files
   for idx = 1:N
       fname = fullfile(output_dir, sprintf('result_%d.mat', idx));
       if exist(fname, 'file'), continue; end  % skip already done
       
       % Check time budget before each iteration
       if toc(t0) > TIME_LIMIT
           fprintf('TIME LIMIT reached at idx=%d, stopping gracefully.\n', idx);
           break;
       end
       
       % Set random seed for reproducibility
       rng(<seed> + idx, 'twister');
       
       % Execute one unit of work
       [cost, sol] = algorithm_function(...);
       
       % Save IMMEDIATELY (timeout = hard-kill, unsaved data is lost)
       result = struct('cost', cost, 'sol', sol, 'idx', idx);
       save(fname, '-struct', 'result');
       fprintf('[%d/%d] cost=%.4f \u2713\n', idx, N, cost);
   end
   
   fprintf('Done: %d/%d completed in %.1fs\n', idx, N, toc(t0));
   ```

   > **Why incremental save matters**: v3.0 timeout is a **hard-kill** of the MATLAB process. Any results held only in memory are permanently lost. With incremental save + skip-completed, a killed task can be re-submitted and will resume from where it stopped.

2. **Validate code quality**
   ```
   lint_code(code="<your code>")
   ```
   Fix all errors; warnings are acceptable if understood.

3. **Pre-flight environment check**
   ```
   diagnose()        → CPU/memory available, MATLAB working dir
   sync_status()     → Syncthing device connected
   list_files(".")   → confirm expected files exist
   ```

4. **File-level sync verification** (critical after code changes)
   ```matlab
   % Verify your modified file actually arrived on remote:
   run("c = fileread('methods/<modified_file>.m'); if contains(c, '<UNIQUE_MARKER>'), disp('SYNCED'); else, disp('NOT SYNCED'); end")
   ```
   `sync_status()` only checks device connection, NOT individual file delivery.

5. **Save code to experiment log**
   - Write the exact code that will be executed to `code/main.m`
   - If multiple scripts, save each separately

### Quality Gate
- [ ] Code passes lint_code without errors
- [ ] All data files confirmed present on remote
- [ ] File-level sync verified (fileread + marker)
- [ ] Incremental save pattern in code (for tasks > 5 min)
- [ ] Time window self-termination included (for tasks > 30 min)
- [ ] Code is saved to local experiment log

## Phase 3: EXECUTE

### Objective
Run the experiment reliably, with monitoring and failure recovery.

### Execution Strategy Decision

```
Estimated runtime?
├─ < 10 min  → run(code=..., timeout=600)
├─ 10-60 min → submit_task(code=..., timeout=3600)
└─ > 60 min  → submit_task(code=..., timeout=7200+)
                 MUST use chunking + incremental save

Chunking strategy (for very large batches):
├─ Split by group × run (e.g., RunAblationChunk pattern)
├─ Each chunk: one group + one run × all scenarios
├─ Benefits: avoids MATLAB heap corruption from thousands of evaluations
└─ Each chunk is independently resumable via skip-completed

Number of independent executions?
├─ 1-3   → submit all in parallel (up to 3 concurrent)
├─ 4-10  → submit in batches of 3
└─ > 10  → submit in batches, monitor queue (max 5 queued)
```

### Monitoring Protocol

```
After submission:
1. Record task_id in metadata.json
2. Wait 30s (cold start), then check:
   get_task_status(task_id)
3. Periodically check output:
   get_task_output(task_id, tail_lines=20)
4. On completion, verify:
   - Exit status is "completed" (not "failed" or "timeout")
   - Output contains expected success markers
   - Result files exist: list_files("<output_dir>")
```

### Failure Recovery

| Failure | Recovery Action |
|---------|----------------|
| MATLAB_ERROR | Read error message, fix code, re-submit |
| TIMEOUT | Increase timeout, or split into chunks |
| QUEUE_FULL | Wait for running tasks, then re-submit |
| Partial results | Check which models completed, submit only missing |

### Quality Gate
- [ ] All tasks completed successfully
- [ ] Result files verified to exist
- [ ] No silent failures (check output for error patterns)

## Phase 4: ANALYZE

### Objective
Transform raw results into statistical evidence.

### Actions

1. **Collect results**
   ```
   inspect("<result_dir>/model_1_<algo>_<tag>.mat")  → check structure
   run("load('<result_file>'); disp(result.cost)")    → read values
   ```

2. **Aggregate across runs and scenarios**
   ```matlab
   % Typical aggregation pattern
   run("
     addpath(fullfile(pwd, 'utils'));
     results_dir = '<path_to_run_dir>';
     stats = computeResultStats(results_dir);
     fprintf('Mean: %.4f, Std: %.4f\n', stats.mean_cost, stats.std_cost);
   ")
   ```

3. **Cross-group comparison** (for ablation/comparison)
   - Compute MRE (Mean Relative Error) vs. best
   - Friedman ranks across scenarios
   - Wilcoxon signed-rank test for pairwise significance
   - Effect size (Cohen's d or rank-biserial correlation)

4. **Generate visualizations**
   ```
   save_figure(figure_code="<plotting code>", filename="<descriptive_name>")
   ```
   Common plot types:
   - Box plots: distribution comparison across groups
   - Convergence curves: algorithm progress over iterations
   - Bar charts with error bars: mean ± std comparison
   - Heatmaps: parameter sensitivity landscapes

### Quality Gate
- [ ] Statistics computed over all runs (no missing data)
- [ ] Significance tests appropriate for sample size
- [ ] Figures are publication-quality (≥200 DPI, labeled axes)

## Phase 5: REPORT

### Objective
Create a permanent, searchable record of the experiment.

### Report Structure

```markdown
# Experiment Report: <Title>

## Metadata
- **ID**: YYYY-MM-DD_<name>
- **Date**: <ISO timestamp>
- **Type**: ablation | comparison | sensitivity | validation
- **Status**: completed | partial | failed

## Hypothesis
<What this experiment tests and expected outcome>

## Configuration
<Table of all parameters>

## Results Summary
<Key metrics table>

## Statistical Analysis
<Significance tests, confidence intervals>

## Figures
<References to generated figures>

## Conclusions
<What the results mean for the paper>

## Raw Data Location
<Remote path to .mat files>
```

### Actions
1. Generate `report.md` in experiment folder
2. Update `index.json` with new entry
3. If results are paper-worthy, note which section/table they support

## Experiment Continuation

When an experiment needs follow-up (common in iterative research):

1. **Reference parent experiment** in metadata (`parent_id` field)
2. **Document what changed** and why
3. **Preserve original** — never overwrite previous experiment logs
4. **Link in index** — cross-reference related experiments

## Parallel Experiment Management

When running multiple experiments simultaneously:

```
Batch submission pattern:
1. Prepare all code variants
2. Submit up to 3 tasks simultaneously
3. Track all task_ids in a batch manifest
4. Monitor with list_tasks (shows all running/queued)
5. As tasks complete, submit next batch
6. After all complete, run unified analysis
```

**Queue awareness**: Max 5 queued + 3 running = 8 total. Don't exceed.
