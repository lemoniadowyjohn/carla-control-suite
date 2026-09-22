# Disk reclamation candidates — audit only

Audited: 2026-09-23 (no deletion, move, cleanup, or Git maintenance was
performed).  This report is a review queue, not authorization to remove any
path.

## Baseline and exclusions

* Production baseline inspected: `origin/integration/production-large-map-20260918`
  at `d06995ec15ee07b9bfcc6671580394c3a5b03691`.
* Space at audit time: C: 23.88 GiB free; F: 0.72 GiB free; G: 209.65 GiB
  free.  New work for this audit is isolated on G:.
* No Git object directory, source file, map-of-record candidate file, or report
  JSON/Markdown content is proposed for deletion.
* The current campaign manifest identifies its governed XODR payloads in
  `campaigns/ingolstadt_cooked_perception_v1/candidate/`; it does not identify
  any `campaigns/ingolstadt_cooked_perception_v1/regen/` directory as the
  current map-of-record.  A coordinator must nevertheless verify any selected
  run against the current artifact receipt before removal.

## Ranked candidates requiring coordinator approval

| Rank | Candidate path | Measured size | Why it is reclaimable-without-risk candidate |
| --- | --- | ---: | --- |
| 1 | `C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\campaigns\\ingolstadt_cooked_perception_v1\\regen\\20260902T151513Z` | 3.95 GiB | Historical regeneration intermediate; not referenced by the checked campaign manifest's governed payload entries. |
| 2 | `...\\regen\\20260905T195239Z` | 3.59 GiB | Same review condition. |
| 3 | `...\\regen\\20260905T173020Z` | 3.59 GiB | Same review condition. |
| 4 | `...\\regen\\20260905T152438Z` | 3.59 GiB | Same review condition. |
| 5 | `...\\regen\\20260905T124135Z` | 3.59 GiB | Same review condition. |
| 6 | `...\\regen\\20260904T210614Z` | 3.59 GiB | Same review condition. |
| 7 | `...\\regen\\20260904T193213Z` | 3.45 GiB | Same review condition. |
| 8 | `...\\regen\\20260817T221616Z` | 3.42 GiB | Same review condition. |
| 9 | `...\\regen\\20260819T142310Z` | 3.41 GiB | Same review condition. |
| 10 | `...\\regen\\20260819T150903Z` | 3.41 GiB | Same review condition. |
| 11 | `...\\regen\\20260819T153954Z` | 3.41 GiB | Same review condition. |
| 12 | `...\\regen\\20260827T135439Z_EXPERIMENTAL_heading_smoothing` | 2.94 GiB | Explicit experimental intermediate; preserve report/manifest evidence, verify no receipt reference before removal. |
| 13 | `...\\regen\\20260902T124414Z_EXPERIMENTAL_heading_smoothing_v2_recompute` | 2.88 GiB | Explicit experimental intermediate; same verification requirement. |
| 14 | `...\\regen\\20260817T211027Z` | 2.11 GiB | Historical regeneration intermediate; same verification requirement. |
| 15 | `...\\regen\\20260904T203247Z` | 1.72 GiB | Historical regeneration intermediate; same verification requirement. |
| 16 | `...\\regen\\20260905T115232Z` | 1.45 GiB | Historical regeneration intermediate; same verification requirement. |
| 17 | `...\\regen\\20260817T202220Z` | 1.43 GiB | Historical regeneration intermediate; same verification requirement. |
| 18 | `...\\regen\\20260817T234901Z` | 0.16 GiB | Historical regeneration intermediate; same verification requirement. |
| 19 | C: and F: worktree `__pycache__` trees | 690.75 MiB total | Rebuildable interpreter cache: C: 2,618 directories / 400.53 MiB; F: 1,378 directories / 290.22 MiB. Remove only after confirming no active process is using a selected worktree. |
| 20 | C: and F: worktree `.pytest_cache` trees | 18.16 MiB total | Rebuildable pytest cache: C: 15 directories / 6.23 MiB; F: 21 directories / 11.93 MiB. |
| 21 | `C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\build\\lib` | 7.16 MiB | Generated build output, not source authority. Compare to a clean build only if a packaging owner needs it. |
| 22 | `F:\\carla-control-suite-worktrees\\runtime-tile-subset-v1-20260914\\build\\lib` | 7.59 MiB | Generated build output in an old worktree, not source authority. |

The 18 `regen` directories total **55.54 GB** (decimal bytes measured:
55,538,240,608).  They are the only large class identified in this audit.

## Tile-based FBX probe replicas

The audit found **414** directories matching
`*_TILE_BASED_FBX_GENERATION_PROBE` across registered C:/F: worktrees,
totalling **203.08 MiB** (212,941,058 bytes).  Each location is under that
worktree's `reports/production_readiness/` root; all share the exact suffix
pattern above, so this is an exhaustive path selector rather than a basename
heuristic.

| Exact size / summary condition | Count | Candidate selector | Assessment |
| --- | ---: | --- | --- |
| 493,577 bytes; `PROBE_RESULT.json` present | 234 | `<worktree>\\reports\\production_readiness\\* _TILE_BASED_FBX_GENERATION_PROBE` (without the displayed space) | The JSON records the probe finding; raw files are reviewable as redundant replicas. |
| 493,576 bytes; `PROBE_RESULT.json` present | 30 | Same selector | Same. |
| 493,575 bytes; `PROBE_RESULT.json` present | 30 | Same selector | Same. |
| 1,818,035 bytes; `PROBE_RESULT.json` present | 30 | Same selector | Same. |
| 493,913 bytes; `PROBE_RESULT.json` present | 4 | Same selector | Same. |
| Other nonzero sizes; summary JSON present | 7 | Same selector | Same. |
| 491,053--491,055 bytes; no summary JSON | 16 | Same selector | **Do not delete** until a replacement summary is identified. |
| Empty directories; no summary JSON | 63 | Same selector | Empty, but retain until worktree ownership is confirmed. |

The individual replica paths are mechanically enumerable without touching
content:

```powershell
git worktree list --porcelain |
  Select-String '^worktree ' |
  ForEach-Object { $_.Line.Substring(9) } |
  Where-Object { $_ -match '^[CF]:' } |
  ForEach-Object {
    Get-ChildItem (Join-Path $_ 'reports/production_readiness') -Directory \
      -Filter '*_TILE_BASED_FBX_GENERATION_PROBE'
  }
```

This report intentionally does not recommend deleting a probe directory whose
only evidence is the directory itself.  A `PROBE_RESULT.json` in the same
directory is necessary but not by itself sufficient approval to delete the
raw probe assets.

## Recommended safe next action

1. Coordinator selects a small, explicit list of historical `regen` run IDs.
2. Before removal, independently resolve the current final-artifact receipt
   and confirm none of its path/SHA parent chain points into those run IDs.
3. Remove only selected non-report binary intermediates, then remeasure free
   space and record the action in a separate deletion log.
4. Treat all F: cleanup as urgent but do not touch active worktrees, Git
   objects, or unreviewed evidence without their owners' confirmation.
