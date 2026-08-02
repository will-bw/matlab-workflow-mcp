# Analysis & Reporting

## Overview

This document defines how to analyze experiment results and generate structured reports suitable for academic paper writing. The goal is to transform raw MATLAB outputs into statistical evidence and publication-ready narratives.

## Statistical Analysis Toolkit

> **Note**: Code templates below use Paper2 project conventions as examples (`computeResultStats` utility, `run_%d` directory pattern, 56 scenarios). Adapt function names, directory layouts, and scenario counts to your actual project.

### Basic Descriptive Statistics

For any result set, compute:
```matlab
% Aggregate pattern (run remotely via MCP)
% Example uses Paper2's computeResultStats utility; adapt to your project's analysis functions
run("
  addpath(fullfile(pwd, 'utils'));
  stats = computeResultStats('<results_dir>');
  fprintf('N=%d\n', stats.n_files);
  fprintf('Mean=%.4f, Std=%.4f\n', stats.mean_cost, stats.std_cost);
  fprintf('Min=%.4f, Max=%.4f, Median=%.4f\n', stats.min_cost, stats.max_cost, stats.median_cost);
  fprintf('Mean time=%.2fs\n', stats.mean_time);
")
```

### Comparative Statistics (Ablation / Comparison)

When comparing multiple groups:

| Metric | Formula | Use Case |
|--------|---------|----------|
| MRE | mean((cost_g - best) / best) per scenario | Overall relative performance |
| Friedman rank | mean(rank across scenarios) | Non-parametric ranking |
| Wilcoxon p-value | signrank(group_g - group_ref) | Pairwise significance |
| Effect size | rank-biserial correlation | Practical significance |
| Success rate | count(cost < threshold) / N | Reliability metric |

### Analysis Code Template

```matlab
% Cross-group comparison (run remotely)
% Example: Paper2-style ablation with run_%d subdirectories and 56 scenarios
run("
  addpath(fullfile(pwd, 'utils'));
  
  groups = {'<group1_dir>', '<group2_dir>', ...};
  n_groups = length(groups);
  n_scenarios = 56;   % adapt to your project's scenario count
  n_runs = 15;
  
  % Aggregate: mean cost per scenario per group
  scenario_means = zeros(n_groups, n_scenarios);
  for g = 1:n_groups
      for run_idx = 1:n_runs
          run_dir = fullfile(groups{g}, sprintf('run_%d', run_idx));
          stats = computeResultStats(run_dir);
          scenario_means(g,:) = scenario_means(g,:) + stats.costs' / n_runs;
      end
  end
  
  % MRE
  global_bests = min(scenario_means, [], 1);
  for g = 1:n_groups
      mre(g) = mean((scenario_means(g,:) - global_bests) ./ global_bests);
  end
  
  % Friedman ranks (correct: convert sort indices to rank matrix)
  rank_mat = zeros(size(scenario_means));
  for j = 1:size(scenario_means, 2)
      [~, idx] = sort(scenario_means(:, j));
      rank_mat(idx, j) = 1:n_groups;  % assign rank 1..N to each group
  end
  friedman_ranks = mean(rank_mat, 2);  % average rank per group
  
  % Wilcoxon (vs best group)
  [~, best_g] = min(mean(scenario_means, 2));
  for g = 1:n_groups
      if g ~= best_g
          [p_vals(g), ~] = signrank(scenario_means(g,:) - scenario_means(best_g,:));
      end
  end
  
  % Display
  fprintf('\\n=== COMPARISON RESULTS ===\\n');
  for g = 1:n_groups
      fprintf('Group %d: MRE=%.4f, Rank=%.2f, Mean=%.1f\\n', ...
          g, mre(g), friedman_ranks(g), mean(scenario_means(g,:)));
  end
")
```

### Significance Thresholds

| p-value | Notation | Interpretation |
|---------|----------|----------------|
| p > 0.05 | n.s. | Not significant |
| p ≤ 0.05 | * | Significant |
| p ≤ 0.01 | ** | Highly significant |
| p ≤ 0.001 | *** | Very highly significant |

## Visualization Standards

### Figure Quality Requirements
- Resolution: ≥ 200 DPI (300 DPI for final submission)
- Font size: ≥ 8pt for labels, ≥ 10pt for titles
- Line width: ≥ 1.5pt for main curves
- Color-blind friendly palettes preferred
- Always label axes with units
- Include legend when multiple series present

### Common Plot Types

**1. Box Plot (Distribution Comparison)**
```matlab
save_figure(figure_code="
  load('<aggregated_data>.mat');
  figure('Position', [100 100 800 400]);
  boxplot(cost_matrix, 'Labels', {'Group1', 'Group2', 'Group3'});
  ylabel('Cost');
  title('Cost Distribution by Group');
  grid on;
", filename="boxplot_comparison")
```

**2. Convergence Curve**
```matlab
save_figure(figure_code="
  load('<result>.mat', 'history');
  figure('Position', [100 100 600 400]);
  semilogy(history.best_costs, 'LineWidth', 1.5);
  xlabel('Iteration'); ylabel('Best Cost');
  title('Convergence Curve');
  grid on;
", filename="convergence")
```

**3. Bar Chart with Error Bars**
```matlab
save_figure(figure_code="
  means = [<values>]; stds = [<values>]; labels = {'G1','G2','G3'};
  figure('Position', [100 100 600 400]);
  bar(means); hold on;
  errorbar(1:length(means), means, stds, 'k.', 'LineWidth', 1.5);
  set(gca, 'XTickLabel', labels);
  ylabel('Mean Cost'); title('Group Comparison');
  grid on;
", filename="bar_comparison")
```

**4. Parameter Sensitivity Heatmap**
```matlab
save_figure(figure_code="
  load('<sweep_results>.mat');
  figure('Position', [100 100 600 500]);
  imagesc(param_values_x, param_values_y, cost_matrix);
  colorbar; xlabel('Param X'); ylabel('Param Y');
  title('Cost Landscape');
", filename="sensitivity_heatmap")
```

## Report Generation

### report.md Template

```markdown
# Experiment Report: <Title>

## Summary
| Field | Value |
|-------|-------|
| ID | <experiment_id> |
| Date | <YYYY-MM-DD> |
| Type | <ablation/comparison/sensitivity> |
| Duration | <total time> |
| Status | <completed/partial> |

## Hypothesis
<Clear statement of what was tested and expected outcome>

## Experimental Design
- **Groups**: <N groups, briefly described>
- **Scenarios**: <N scenarios>
- **Runs per scenario**: <N>
- **Total executions**: <groups × scenarios × runs>
- **Key parameters**: <table>

| Parameter | Value |
|-----------|-------|
| ... | ... |

## Results

### Primary Metrics

| Group | Mean Cost | Std | MRE | Rank | 
|-------|-----------|-----|-----|------|
| ... | ... | ... | ... | ... |

### Statistical Tests

| Comparison | p-value | Significance |
|-----------|---------|--------------|
| A vs Full | <p> | *** |
| B vs Full | <p> | n.s. |

### Key Observations
1. <Observation 1>
2. <Observation 2>

## Figures
- ![Comparison](figures/<name>.png)

## Conclusions
<What these results mean for the paper's claims>

## Paper Integration
- Supports: <Section X, Table Y, Figure Z>
- Claim validated: <specific claim>

## Reproducibility
- Remote results: <path on Windows>
- Code: [code/main.m](code/main.m)
- Seed: <random seed used>
```

## Multi-Experiment Comparison

When comparing across multiple experiments (e.g., "did the latest parameter tuning improve over the previous run?"):

1. Load both experiments' `results/summary.json`
2. Compute delta metrics
3. Generate a comparison table
4. Note any confounding differences (different seeds, different scenarios)

## Automated Analysis Workflow

After experiment completion, the agent should:

```
1. Verify all results exist (list_files on remote)
2. Run aggregate statistics (remote computation)
3. Transfer summary (small JSON/MAT via run + save)
4. Generate key figures (save_figure)
5. Wait for Syncthing sync (2-3s)
6. Write report.md locally
7. Update metadata.json with results.summary
8. Update index.json
```

## Paper Writing Integration

### From Results to Paper Text

When the user asks to write paper sections based on results:

1. **Locate relevant experiments** via index.json tags/paper_section
2. **Extract key numbers** from report.md or results/summary.json
3. **Format for LaTeX** if needed:
   - Tables: generate `\begin{table}...\end{table}` 
   - Numbers: use consistent precision (4 decimal for costs, 2 for times)
   - Significance: use standard notation (*, **, ***)

### Consistency Checks
- Ensure numbers in text match the experiment log
- Flag if citing results from a superseded experiment
- Verify figure references match actual generated figures
