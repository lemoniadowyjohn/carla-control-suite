# Codex PROMPT OO: investigate the real scriptable-vs-GUI-only boundary for post-ingestion map polish

## Context

CARLA's map creation docs describe several follow-on customization steps after basic `make import`
ingestion (**PROMPT NN**): traffic-light/stop-sign placement review, sub-level organization, and
pedestrian navigation-mesh generation. It is not yet established, for this repo's actual use case, how
much of this is genuinely automatable via CARLA's Python API / Unreal Editor Utility Widgets versus
requiring interactive GUI work in the Unreal Editor. Do not assume either extreme -- investigate for
real.

## Hard prerequisite gate -- check this FIRST

This task needs a real ingested map to investigate against.

1. Confirm **PROMPT NN**'s evidence artifact
   (`reports/production_readiness/*_MAP_INGESTION_MAKE_IMPORT/INGESTION_REPORT.md`) shows a genuine
   successful ingestion with confirmed `Unreal/CarlaUE4/Content/` output. If missing or not passed,
   STOP and report that NN must complete first -- do not investigate against a hypothetical/unbuilt map.

## Task

For each of the following, determine concretely (by reading CARLA's actual source/docs for the engine
version built in PROMPT MM, and where possible by actually exercising it against the real ingested
map) whether it is scriptable headlessly, requires the Editor GUI but can still run unattended via
`UnrealEditor-Cmd`/`UE4Editor-Cmd` with a script, or is genuinely interactive-only:

1. **Traffic light / stop sign placement review** -- CARLA auto-generates these from the `.xodr`
   during ingestion per its docs; determine whether the auto-placement is generally trustworthy for a
   real city-scale OSM-derived map (which may have OpenDRIVE signal data of uneven quality -- this
   repo's own audit tooling, e.g. anything under `ultimate_pipeline/quality/` touching signs/lights,
   may be informative context for what quality issues to expect) or whether manual review is genuinely
   necessary, and if so, whether that review can be scripted as an automated *report* (flag likely-bad
   placements) even if the actual fix requires a human.
2. **Sub-levels** -- determine whether this repo's single ~32267-road map needs sub-level splitting at
   all for practical loading/editing (large open-world UE4 projects often do), and if so, whether
   CARLA/UE4 exposes a scriptable way to auto-partition, or whether this is Editor-GUI-only.
3. **Pedestrian navigation-mesh generation** -- CARLA's docs reference a "generate the pedestrian
   navigation information" step; determine the exact command/script for this (this is very likely
   scriptable/CLI-based given CARLA ships a documented workflow for it -- confirm and use it rather
   than assuming it needs the GUI) and, if possible, actually run it against the real ingested map.

## Evidence

Write a dated status artifact to
`reports/production_readiness/<TIMESTAMP>_POST_INGESTION_AUTOMATION_SURFACE/AUTOMATION_SURFACE.md`
covering all three items above with a clear verdict per item: **scriptable (with the exact
command/API)**, **GUI-required (with exactly what's needed and why it can't be scripted)**, or
**scriptable-as-report-only (auto-flags issues, human still fixes)**. This should give a future session
(human or Codex) a precise, evidence-based map of what can be automated end-to-end versus what always
needs a human at the Editor.

## Constraints

- Do not fabricate a "scriptable" verdict without actually confirming the command/API exists and, where
  feasible given the real ingested map from PROMPT NN, running it for real -- a documentation citation
  alone is not sufficient evidence for a "scriptable" verdict, actually exercise it.
- Do not attempt a live CARLA load/drive test -- same GPU-driver TDR livelock caveat as PROMPT NN
  applies; this task is about the Editor/CLI-side automation surface, not live simulation.
- New commits only, never amend. Never force-push. Never skip hooks.
- Full test suite via bare `pytest` must stay green.
- Push your branch and report status; do not merge into `integration/session-batch1-20260912` yourself.
