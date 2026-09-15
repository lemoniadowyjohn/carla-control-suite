# Documentation Information Architecture

Status: proposed target + reconciliation against what actually exists on this branch as of baseline
`2e020d9b`. Per the audit brief: **no historical files were moved in this pass.** This document plans
a migration; `docs/index.md` (written alongside this file) is the navigation authority for what
exists *today*.

## Important finding: the docs tree has already evolved past the brief's original proposal

The audit brief proposed a fresh `docs/{architecture,map_quality,operations,research,governance,
reference,deprecated}/` skeleton. Checking the actual current state of this branch found that
**most of this already exists, but organized differently** than what was proposed — built by prior
work on this branch (Codex and/or earlier Claude sessions) independently of this audit:

| Brief's proposed path | What actually exists |
|---|---|
| `docs/architecture/overview.md` | `docs/ARCHITECTURE.md` (top-level, not in a subdirectory) |
| `docs/map_quality/QUALITY_CONTRACT.md` | Did not exist before this audit; `PRODUCTION_MAP_QUALITY_CONTRACT.yaml` (repo root, per this audit's explicit required-output list) now serves this role |
| `docs/map_quality/MAP_OF_RECORD.md` | `docs/runtime/MAP_OF_RECORD.md` (a `runtime/` directory not in the brief's proposal at all) |
| `docs/operations/RUNBOOK.md`, `CARLA_RUNTIME.md` | `docs/runtime/CARLA_RUNTIME_REQUIREMENTS.md`, `docs/REPRODUCIBILITY.md` (different names/locations) |
| `docs/research/THESIS_RQ_CONTRACT.md` | `docs/research/THESIS_RQ_CONTRACT.md` -- **matches exactly** |
| `docs/research/THESIS_TO_CURRENT_PROGRESS.md` | `docs/research/THESIS_TO_CURRENT_PROGRESS.md` -- **matches exactly** (this file's content traces back to this session's own earlier WS-6 work) |
| `docs/research/CLAIM_BOUNDARIES.md`, `EVIDENCE_INDEX.md`, `EXPERIMENT_PROTOCOLS.md` | all three exist, matching exactly |
| `docs/governance/REPOSITORY_GOVERNANCE.md` | `docs/REPOSITORY_GOVERNANCE.md` (top-level, not in a `governance/` subdirectory) |
| `docs/reference/*` | does not exist yet |
| `docs/deprecated/*` | does not exist yet |
| (not in brief's proposal) | `docs/hardening/00-08_*.md` (8 files), `docs/remediation/ACTIVE_CALL_GRAPH.md`, `docs/submission/perception_rca_final.md`, `docs/KNOWN_LIMITATIONS.md`, `docs/REPO_HEALTH.md` -- all real, substantive, pre-existing content the brief's proposal didn't account for |
| (not in brief's proposal) | `docs/02_CLAUDE_C0_REVIEW_PROMPT.md`, `docs/N04_CLAUDE_C0_PACKET.md`, `docs/N19_CLAUDE_C1_PACKET.md`, `docs/R05_CARLA_0916_CROSSWALK_OBJECT_SCHEMA.md` -- older, pre-existing root-level files from earlier in this repo's history |

**Conclusion**: rather than creating a parallel, competing directory structure, this document
proposes reconciling the brief's target with what's real -- moving/renaming existing files into the
proposed subdirectory structure where that adds real value, and explicitly keeping the `runtime/`,
`hardening/`, `remediation/`, and `submission/` directories the brief didn't anticipate, since they
already hold real, non-redundant content.

## Reconciled target structure

```
docs/
  index.md                          [NEW -- this pass -- navigation authority]

  architecture/
    overview.md                     [MOVE from docs/ARCHITECTURE.md -- OpenCode]
    pipeline_stages.md               [NEW, derived from PIPELINE_DEPENDENCY_GRAPH.json]
    dependency_graph.md               [NEW, derived from PIPELINE_DEPENDENCY_GRAPH.json]
    TARGET_PIPELINE_STAGE_GRAPH.md    [EXISTS -- this pass]

  map_quality/
    QUALITY_CONTRACT.md               [the repo-root PRODUCTION_MAP_QUALITY_CONTRACT.yaml is the
                                        machine-readable source of truth; this would be a prose
                                        companion -- NEW, future pass]
    JUNCTIONS_AND_CONNECTORS.md        [EXISTS -- this pass]
    JUNCTIONS_AND_ROUNDABOUTS.md        [EXISTS -- this pass]
    HORIZONTAL_GEOMETRY.md               [NEW, future pass -- content exists in
                                          reports/production_readiness/20260906T170000Z/ and the
                                          gap register, not yet a standalone prose doc]
    LANES_AND_CROSS_SECTIONS.md           [NEW, future pass]
    ELEVATION_AND_STRUCTURES.md            [NEW, future pass]
    SEMANTICS_AND_OSM_MATCHING.md           [NEW, future pass]
    VISUAL_AND_COOKED_QA.md                  [NEW, future pass]
    REGRESSION_CORPUS.md                      [NEW -- the worst-road lists in the gap register and
                                               PIPELINE_DEPENDENCY_GRAPH.json should be consolidated
                                               here as fixtures land]
    MAP_OF_RECORD.md                          [MOVE from docs/runtime/MAP_OF_RECORD.md -- OpenCode]

  operations/
    INSTALL.md, CONFIGURATION.md               [NEW, future pass]
    RUNBOOK.md                                  [MOVE/derive from docs/REPRODUCIBILITY.md -- OpenCode]
    TROUBLESHOOTING.md                           [NEW, future pass]
    RELEASE_PROCESS.md                            [derive from docs/REPOSITORY_GOVERNANCE.md's
                                                   release-receipt requirements -- OpenCode]
    CARLA_RUNTIME.md                               [MOVE from docs/runtime/CARLA_RUNTIME_REQUIREMENTS.md
                                                     -- OpenCode]

  research/                                         [ALREADY CORRECT -- no action needed]
    THESIS_RQ_CONTRACT.md, THESIS_TO_CURRENT_PROGRESS.md, CLAIM_BOUNDARIES.md,
    EXPERIMENT_PROTOCOLS.md, EVIDENCE_INDEX.md

  governance/
    REPOSITORY_GOVERNANCE.md                        [MOVE from docs/REPOSITORY_GOVERNANCE.md -- OpenCode]
    EVIDENCE_HASHING.md                              [NEW, future pass]
    BRANCH_POLICY.md                                  [NEW, future pass -- should document the
                                                       main-branch-orphan situation and the
                                                       review/stabilize branch lineage explicitly]
    RELEASE_RECEIPTS.md                                [NEW, future pass]

  reference/
    CLI.md, CONFIG_SCHEMA.md, ARTIFACT_SCHEMAS.md, MAP_REGISTRY.md   [all NEW, future pass]

  deprecated/
    README.md, MANIFEST.yaml                          [NEW, future pass -- OpenCode's eventual
                                                        mechanical migration target for the older
                                                        root-level docs/*.md packet files and
                                                        anything else retired during reconciliation]

  # Kept, not reorganized -- real content the brief's proposal didn't anticipate:
  hardening/          (8 files, post-audit hardening design docs)
  remediation/         (ACTIVE_CALL_GRAPH.md)
  submission/           (perception_rca_final.md)
  KNOWN_LIMITATIONS.md   (top-level; candidate for governance/ or research/, not decided here)
  REPO_HEALTH.md          (top-level; candidate for operations/, not decided here)
```

## What this pass actually did

- Created `docs/index.md` (navigation authority for the CURRENT real structure, not the proposed one).
- Created `docs/architecture/TARGET_PIPELINE_STAGE_GRAPH.md`, `docs/map_quality/JUNCTIONS_AND_CONNECTORS.md`,
  `docs/map_quality/JUNCTIONS_AND_ROUNDABOUTS.md` (all required outputs of this audit).
- Corrected one stale CI claim in `README.md` (see the audit's `MAP_QUALITY_GAP_REGISTER.json` GAP-031
  and the CI-verification section of `CLAUDE_PRODUCTION_MAP_AUDIT.md`).
- Did **not** move, rename, or delete any existing file. All "[MOVE ... -- OpenCode]" annotations
  above are proposals for a future mechanical-migration pass, per the audit brief's explicit
  instruction ("Do not move historical files in this Claude stage. OpenCode will do the mechanical
  migration later.").

## Why this reconciliation approach, not a fresh parallel structure

Creating the brief's proposed skeleton verbatim alongside the real, already-evolved structure would
produce two competing, partially-redundant documentation trees -- exactly the kind of confusion good
information architecture is supposed to prevent. Reconciling (documenting what's real, proposing
targeted moves rather than parallel duplication) is more useful and lower-risk than either blindly
following a now-stale proposal or silently ignoring it.
