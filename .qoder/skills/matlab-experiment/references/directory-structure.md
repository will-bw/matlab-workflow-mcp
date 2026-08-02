# Experiment Directory Structure

## Overview

This document defines the local file organization system for experiment artifacts. The structure is designed for:
- Quick retrieval of any past experiment
- Clear separation of code, data, and analysis
- Compatibility with version control (Git)
- Support for cross-experiment comparison

## Root Location

The experiment log lives inside the user's project directory:
```
<project_root>/experiment_log/
```

The agent should ask the user for their project root if unknown, or discover it from context (e.g., the workspace being worked in).

## Top-Level Structure

```
experiment_log/
├── index.json                          # Master index (always present)
├── templates/                          # Reusable templates
│   ├── metadata_template.json
│   └── report_template.md
├── YYYY-MM-DD_<experiment-id>/         # Individual experiments
│   ├── metadata.json
│   ├── code/
│   ├── results/
│   ├── figures/
│   └── report.md
└── ...
```

## Individual Experiment Folder

```
YYYY-MM-DD_<experiment-id>/
├── metadata.json              # Full experiment metadata (see metadata-schema.md)
├── code/                      # All executed code (verbatim)
│   ├── main.m                 # Primary execution script
│   ├── config.m               # Parameter configuration (if separate)
│   └── analysis.m             # Post-hoc analysis code (if any)
├── results/                   # Downloaded or synced result summaries
│   ├── summary.json           # Aggregated metrics
│   ├── stats.mat              # Statistical results (if transferred)
│   └── raw/                   # Raw result files (optional, large)
│       └── ...
├── figures/                   # Generated figures (synced via Syncthing)
│   ├── convergence.png
│   ├── boxplot_comparison.png
│   └── ...
└── report.md                  # Structured analysis report
```

## Naming Conventions

### Experiment IDs
- Format: `YYYY-MM-DD_<kebab-case-descriptor>`
- The date is the experiment **creation** date
- Descriptor should be specific enough to distinguish from similar experiments

Examples:
```
2026-08-02_ablation-three-innovations
2026-08-02_comparison-e3-dv10-all-algos
2026-08-03_sensitivity-subpop-2-to-10
2026-08-03_validation-single-model-debug
```

### Figure Files
- Use descriptive names: `<what-is-shown>_<context>.<ext>`
- Examples: `boxplot_ablation-cost.png`, `convergence_full-vs-baseline.png`
- Prefer PNG for raster (200+ DPI), SVG/PDF for vector

### Code Files
- `main.m` — the primary execution script (always present)
- Additional files named by function: `analysis.m`, `visualization.m`
- Code must be the **exact** version that was executed
- `code_hash` in metadata.json: fill when you need change-detection across re-runs (e.g., verifying that a repeated experiment used identical code). Compute via `run("fprintf('%s', char(java.security.MessageDigest.getInstance('SHA-256').digest(fileread('code/main.m'))))")`. Optional for one-off experiments.

## index.json Management

The index is the entry point for querying experiment history.

### When to Update
- **Create entry**: at experiment DESIGN phase (status: "designed")
- **Update status**: at each phase transition
- **Add results summary**: at ANALYZE phase
- **Final update**: at REPORT phase (status: "completed")

### Query Patterns

**Find by type:**
```
Filter index.experiments where type == "ablation"
```

**Find by paper section:**
```
Filter index.experiments where paper_section contains "Table 2"
```

**Find recent:**
```
Sort index.experiments by created_at descending, take first N
```

**Find by tag:**
```
Filter index.experiments where tags contains "innovation-1"
```

## Batch Experiment Organization

For experiments with multiple groups (ablation, comparison), use sub-structure:

```
2026-08-02_ablation-innovations/
├── metadata.json              # Parent metadata (contains all groups)
├── experiment_plan.json       # Full experiment matrix definition
├── code/
│   ├── group_baseline.m
│   ├── group_component1.m
│   ├── group_component2.m
│   └── group_full.m
├── results/
│   ├── summary.json           # Cross-group comparison
│   ├── baseline/              # Per-group results (if downloaded)
│   ├── component1/
│   └── ...
├── figures/
│   ├── comparison_boxplot.png
│   └── hierarchy_check.png
└── report.md
```

## Remote vs. Local Storage

### What stays REMOTE (Windows server):
- Large .mat result files (per-model, per-run)
- Intermediate computation artifacts
- Terrain/model data files

### What comes LOCAL (via Syncthing or transfer):
- Figures (via Syncthing `exports/` directory)
- Summary statistics (small .mat or .json)
- Aggregated result matrices

### What is created LOCAL (by the agent):
- `metadata.json` — experiment provenance
- `report.md` — analysis narrative
- `index.json` — master index
- Code copies in `code/` — for archival

## Size Management

- **Do NOT download** large raw result files unless explicitly requested
- **Prefer summaries**: compute statistics remotely, transfer only the summary
- **Figures**: sync via Syncthing (automatic), don't use transfer_file
- **Git-friendly**: add `experiment_log/*/results/raw/` to `.gitignore` if needed

## Retrieval Workflow

When the user asks "what experiments have I run?" or "find the ablation from last week":

```
1. Read experiment_log/index.json
2. Filter/sort by criteria (date, type, tags, status)
3. Present matching experiments as a table
4. If user wants details → read specific metadata.json
5. If user wants results → read report.md or results/summary.json
```

## Migration & Compatibility

- If no `experiment_log/` exists, create it with an empty index
- If `index.json` is missing, scan folders to reconstruct it
- Version field in index.json allows future schema evolution
