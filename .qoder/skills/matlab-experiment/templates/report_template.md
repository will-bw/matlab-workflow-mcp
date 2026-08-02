# Experiment Report: <Title>

## Summary

| Field | Value |
|-------|-------|
| ID | <experiment_id> |
| Date | <YYYY-MM-DD> |
| Type | <ablation / comparison / sensitivity / validation> |
| Duration | <total time> |
| Status | <completed / partial / failed> |

## Hypothesis

<Clear statement of what was tested and the expected outcome.>

## Experimental Design

- **Groups**: <N groups, briefly described>
- **Scenarios**: <N scenarios description>
- **Runs per scenario**: <N>
- **Total executions**: <groups × scenarios × runs>

### Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| <param1> | <value> | <note> |
| <param2> | <value> | <note> |

### Groups

| Group | Description | Key Differences |
|-------|-------------|-----------------|
| <name> | <desc> | <what varies> |

## Results

### Primary Metrics

| Group | Mean | Std | MRE | Rank |
|-------|------|-----|-----|------|
| <name> | <val> | <val> | <val> | <val> |

### Statistical Tests

| Comparison | p-value | Significance | Effect Size |
|-----------|---------|--------------|-------------|
| <A vs B> | <p> | <*/**/***/n.s.> | <d> |

### Key Observations

1. <Observation 1 — what the data shows>
2. <Observation 2 — notable patterns or anomalies>
3. <Observation 3 — implications>

## Figures

<!-- Reference synced figures from figures/ directory -->
- <figure description>: `figures/<filename>.png`

## Conclusions

<What these results mean for the paper's claims. Does the hypothesis hold?
What is the practical significance? Any caveats?>

## Paper Integration

- **Supports**: <Section X, Table Y, Figure Z>
- **Claim validated**: <specific claim from the paper>
- **LaTeX-ready numbers**: <key values formatted for direct insertion>

## Reproducibility

| Item | Location |
|------|----------|
| Code | [code/main.m](code/main.m) |
| Remote results | <path on Windows server> |
| Random seed | <seed value> |
| MATLAB version | <version> |
| Execution date | <ISO timestamp> |

## Notes

<Any additional observations, anomalies, or decisions made during the experiment.>
