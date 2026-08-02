# Experiment Metadata Schema

## Overview

Every formal experiment must produce a `metadata.json` file that captures complete provenance. This enables reproducibility, comparison, and future retrieval.

## metadata.json Schema

```json
{
  "experiment_id": "YYYY-MM-DD_<short-descriptive-name>",
  "title": "Human-readable experiment title",
  "created_at": "ISO-8601 timestamp",
  "completed_at": "ISO-8601 timestamp or null",
  "status": "designed | running | completed | failed | partial",

  "purpose": {
    "hypothesis": "What this experiment tests",
    "expected_outcome": "Quantitative or qualitative expectation",
    "paper_section": "Which paper section this supports (e.g., 'Table 2', 'Section 4.3')"
  },

  "type": "ablation | comparison | sensitivity | validation | scalability",

  "design": {
    "groups": [
      {
        "name": "Group label",
        "description": "What this group represents",
        "parameters": { "key": "value" }
      }
    ],
    "scenarios": "Description of test scenarios (e.g., '56 terrain models')",
    "n_runs": 15,
    "random_seed": 42,
    "independent_variables": ["list of varied factors"],
    "dependent_variables": ["list of measured outcomes"],
    "control_variables": ["list of fixed factors"]
  },

  "execution": {
    "remote_working_dir": "MATLAB pwd on remote (discovered via diagnose)",
    "tasks": [
      {
        "task_id": "MCP task ID",
        "group": "Group name",
        "submitted_at": "ISO-8601",
        "completed_at": "ISO-8601",
        "status": "completed | failed | timeout",
        "duration_seconds": 123.4
      }
    ],
    "total_duration_seconds": 0,
    "matlab_version": "R2022b",
    "parallel_slots_used": 3
  },

  "code": {
    "main_script": "code/main.m",
    "additional_files": ["code/helper.m"],
    "code_hash": "SHA-256 of main script (optional, for change detection)"
  },

  "results": {
    "remote_path": "Path on Windows to result directory",
    "local_path": "Local synced path (if applicable)",
    "summary": {
      "total_executions": 0,
      "successful": 0,
      "failed": 0,
      "key_metrics": {}
    }
  },

  "lineage": {
    "parent_id": "Parent experiment ID (for follow-ups)",
    "related_ids": ["Other related experiment IDs"],
    "supersedes": "Experiment ID this replaces (if any)"
  },

  "tags": ["ablation", "innovation-1", "e3-budget"],
  "notes": "Free-form notes about observations, anomalies, decisions"
}
```

## Field Guidelines

### experiment_id
- Format: `YYYY-MM-DD_<kebab-case-name>`
- Examples: `2026-08-02_ablation-innovation-components`, `2026-08-02_sensitivity-subpop-count`
- Must be unique within the project

### purpose.hypothesis
- Must be falsifiable
- Good: "Adding RRT repair reduces mean cost by ≥5% compared to baseline"
- Bad: "Test if RRT helps"

### design.groups
For **ablation** experiments, follow incremental pattern:
```json
[
  {"name": "Baseline", "description": "No innovations", "parameters": {"subpops": 1, "rrt": false, "init": "uniform"}},
  {"name": "+Component1", "description": "Add innovation 1", "parameters": {"subpops": 1, "rrt": false, "init": "obstacle_aware"}},
  {"name": "+Component2", "description": "Add innovation 2", "parameters": {"subpops": 3, "rrt": false, "init": "uniform"}},
  {"name": "Full", "description": "All innovations", "parameters": {"subpops": 3, "rrt": true, "init": "obstacle_aware"}}
]
```

For **comparison** experiments:
```json
[
  {"name": "Proposed", "parameters": {"algo": "<proposed algorithm>"}},
  {"name": "Baseline-A", "parameters": {"algo": "<competitor A>"}},
  {"name": "Baseline-B", "parameters": {"algo": "<competitor B>"}}
]
```

For **sensitivity** experiments:
```json
[
  {"name": "param=1", "parameters": {"target_param": 1}},
  {"name": "param=3", "parameters": {"target_param": 3}},
  {"name": "param=5", "parameters": {"target_param": 5}},
  {"name": "param=10", "parameters": {"target_param": 10}}
]
```

### execution.tasks
- One entry per submitted MCP task
- For batch experiments with many sub-tasks, record top-level batches
- `duration_seconds` computed from submitted_at to completed_at

### results.summary.key_metrics
Flexible key-value pairs for the most important outcomes:
```json
{
  "mean_cost": 123.45,
  "std_cost": 12.3,
  "mean_time_seconds": 45.2,
  "success_rate": 0.95,
  "mre_vs_best": 0.032
}
```

## index.json Schema

The master index at `experiment_log/index.json` provides quick lookup:

```json
{
  "version": 1,
  "last_updated": "ISO-8601",
  "experiments": [
    {
      "id": "2026-08-02_ablation-innovation",
      "title": "Ablation study of three innovations",
      "type": "ablation",
      "status": "completed",
      "created_at": "ISO-8601",
      "tags": ["ablation", "main-results"],
      "paper_section": "Table 2",
      "folder": "2026-08-02_ablation-innovation/"
    }
  ]
}
```

## Minimal vs. Full Metadata

**Minimal** (required for every logged experiment):
- experiment_id, title, created_at, status
- purpose.hypothesis
- type
- code.main_script (the actual code file must exist)

**Full** (add as experiment progresses):
- design.* (at DESIGN phase)
- execution.* (at EXECUTE phase)
- results.* (at ANALYZE phase)
- lineage.* (if follow-up)

## Updating Metadata

- `metadata.json` is a living document — update it as the experiment progresses
- Never delete fields; set to `null` if not applicable
- Append to `notes` rather than overwriting
- Update `status` at each phase transition
