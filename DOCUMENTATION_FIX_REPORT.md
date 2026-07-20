# Documentation Consistency Fix Report

## Scope

This package applies a documentation-only consistency fix. No application code, database schema, package, or runtime configuration was changed.

## Fixed

1. Unified mandatory reading across `CLAUDE.md`, `PROGRESS.md`, `README.md`, `WORKFLOW_SHORT.md`, and the full Learning Workflow:
   - `CLAUDE.md`
   - `PROGRESS.md`
   - `docs/WORKFLOW_SHORT.md`

2. Updated `README.md` project status:
   - Step 4 Dataset Ingestion completed
   - Step 5 Dataset API is next

3. Unified Green Operations Index:
   - PV Utilization: 25
   - Battery Operation: 25
   - Grid Dependency: 20
   - Battery Health: 20
   - Second-life Battery Bonus: 10

4. Unified canonical enums:

   `ems_mode`
   - auto
   - manual
   - schedule
   - tou_arbitrage
   - peak_shaving
   - self_consumption
   - idle
   - fallback
   - error
   - unknown

   `equipment_status`
   - normal
   - warning
   - fault
   - error
   - offline
   - maintenance
   - unknown

5. Added missing tracking templates:
   - `docs/ANTHROPIC_LEARN_MAP.md`
   - `docs/DECISIONS.md`
   - `docs/OFFICIAL_UPDATE_LOG.md`

6. Preserved:
   - MVP v1 scope
   - Current project Step
   - Learning-by-building workflow
   - Git / GitHub learning rules
   - NVIDIA AI Applied Engineer learning goals
   - Existing data columns and rule thresholds

## Installation

Copy the package contents into the repository root and replace the matching Markdown files.

Before overwriting, review with Git:

```bash
git status
git diff
```

After copying:

```bash
git status
git diff -- CLAUDE.md PROGRESS.md README.md docs/
```

Do not commit until the diff has been reviewed.
