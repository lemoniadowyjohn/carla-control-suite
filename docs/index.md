# Documentation Index

Navigation authority for this repository's documentation. Reflects the **actual current structure**
as of baseline `2e020d9b` (branch `review/claude-independent-audit-20260906`) -- not an aspirational
layout. See `DOCS_INFORMATION_ARCHITECTURE.md` (repo root) for the reconciled target structure and
what a future mechanical migration would move where.

## Start here

- [`../README.md`](../README.md) -- what this repo is, canonical entrypoints, map-of-record identity,
  RQ evidence status, how to reproduce.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) -- current pipeline architecture overview.
- [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) -- step-by-step reproduction instructions.

## Architecture

- [`architecture/TARGET_PIPELINE_STAGE_GRAPH.md`](architecture/TARGET_PIPELINE_STAGE_GRAPH.md) --
  proposed target stage ordering, and why reordering does *not* fix Stage-6 containment (a common
  misconception this document directly corrects with code evidence).
- [`ARCHITECTURE.md`](ARCHITECTURE.md) -- current (not target) architecture.
- `../reports/production_readiness/20260906T170000Z/PIPELINE_DEPENDENCY_GRAPH.json` -- full
  per-stage read/write/domain inventory backing the target-stage-graph document above.

## Map quality

- [`map_quality/JUNCTIONS_AND_CONNECTORS.md`](map_quality/JUNCTIONS_AND_CONNECTORS.md)
- [`map_quality/JUNCTIONS_AND_ROUNDABOUTS.md`](map_quality/JUNCTIONS_AND_ROUNDABOUTS.md)
- `../PRODUCTION_MAP_QUALITY_CONTRACT.yaml` -- the unified acceptance-profile contract
  (`research_release` / `production_candidate` / `runtime_certified`).
- `../MAP_QUALITY_GAP_REGISTER.json` -- the full, ranked (P0-P3) gap list this contract and the
  task graph are built from.
- [`runtime/MAP_OF_RECORD.md`](runtime/MAP_OF_RECORD.md) -- current map-of-record identity and pin
  mechanism.

## Operations / runtime

- [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md)
- [`REPO_HEALTH.md`](REPO_HEALTH.md) -- `up health` packet semantics and status vocabulary.
- [`runtime/CARLA_RUNTIME_REQUIREMENTS.md`](runtime/CARLA_RUNTIME_REQUIREMENTS.md)
- [`runtime/PERCEPTION_CAPTURE_PROTOCOL.md`](runtime/PERCEPTION_CAPTURE_PROTOCOL.md)

## Research

- [`research/THESIS_RQ_CONTRACT.md`](research/THESIS_RQ_CONTRACT.md) -- the real thesis RQ1-5
  definitions and the metric-allow-list contract that catches numbering drift.
- [`research/THESIS_TO_CURRENT_PROGRESS.md`](research/THESIS_TO_CURRENT_PROGRESS.md) -- per-RQ
  baseline-vs-current-state comparison.
- [`research/CLAIM_BOUNDARIES.md`](research/CLAIM_BOUNDARIES.md)
- [`research/EXPERIMENT_PROTOCOLS.md`](research/EXPERIMENT_PROTOCOLS.md)
- [`research/EVIDENCE_INDEX.md`](research/EVIDENCE_INDEX.md)
- [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md)

## Governance

- [`REPOSITORY_GOVERNANCE.md`](REPOSITORY_GOVERNANCE.md) -- immutability rules for thesis questions,
  metric definitions, frozen hashes, map identity, and claim status; provenance-receipt requirements.

## Production readiness (this audit)

- `../CLAUDE_PRODUCTION_MAP_AUDIT.md` -- the master narrative document for this pass.
- `../MAP_QUALITY_GAP_REGISTER.json`, `../PRODUCTION_MAP_QUALITY_CONTRACT.yaml`,
  `../PRODUCTION_MAP_TASK_GRAPH.json`, `../PRODUCTION_MAP_REMEDIATION_PLAN.md`.
- `../reports/production_readiness/20260906T170000Z/` -- raw audit evidence (`A0_AUTHORITY.json`,
  `PIPELINE_DEPENDENCY_GRAPH.json`).

## Historical / design-process documentation (kept as-is, not reorganized this pass)

- [`hardening/`](hardening/) -- 8 post-audit hardening design documents (pipeline map, mutation
  matrix, call graph, hardening proof, drivable-surface stage design, gate-runner design,
  regression report, sha verification, sensor acceptance).
- [`remediation/ACTIVE_CALL_GRAPH.md`](remediation/ACTIVE_CALL_GRAPH.md)
- [`submission/perception_rca_final.md`](submission/perception_rca_final.md)
- `02_CLAUDE_C0_REVIEW_PROMPT.md`, `N04_CLAUDE_C0_PACKET.md`, `N19_CLAUDE_C1_PACKET.md`,
  `R05_CARLA_0916_CROSSWALK_OBJECT_SCHEMA.md` -- earlier-session review/handoff packets.

## Frozen (do not edit)

- `../submission/` -- the archived thesis-submission deliverable. Not imported by production code,
  excluded from test collection. See `REPOSITORY_GOVERNANCE.md` for the immutability policy.
