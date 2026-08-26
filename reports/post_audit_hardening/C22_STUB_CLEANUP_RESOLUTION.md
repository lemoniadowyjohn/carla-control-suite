# C22 — dead/no-op stub cleanup (resolution report)

**Filename note:** the task spec asked for this report at `C22_STUB_CLEANUP.md`, but that path
case-insensitively collides with the pre-existing, git-tracked `reports/post_audit_hardening/C22_stub_cleanup.md`
(the original dispatch/prompt doc from commit 3d1901a8) on this Windows filesystem — Windows paths are
case-insensitive, so `C22_STUB_CLEANUP.md` and `C22_stub_cleanup.md` are literally the same file on disk,
even though git's index tracks them as two different (case-distinct) paths. Writing to the uppercase name
overwrote the physical bytes backing the lowercase git-tracked file. I caught this via `git status`/`git diff`
showing an unexpected diff on a file I hadn't touched, recovered the original content with
`git show HEAD:reports/post_audit_hardening/C22_stub_cleanup.md`, restored it byte-for-byte (confirmed via
`git diff` showing empty), and am instead naming this deliverable report
`C22_STUB_CLEANUP_RESOLUTION.md` to avoid the collision entirely.

Repo: `carla_-main`, worktree `c22-stub-cleanup-20260826`
Branch: `fix/c22-stub-cleanup-20260826` (based on `fix/post-audit-phase-e-junctions-roundabouts-20260803`
@ 3d1901a8)
Base prompt: `reports/post_audit_hardening/C22_stub_cleanup.md` (lowercase — the original dispatch doc,
left untouched; this file is the deliverable it asked for).
Interp: `.venv/Scripts/python.exe` · `UP_DISABLE_CARLA=1` · fully offline, no live CARLA used.

## 1. `ultimate_pipeline/carla_tools/mesh_streamer.py:115` — `MeshStreamer.update(self): pass`

**Found:** `MeshStreamer` already had real, working logic (`load_layer`, `unload_layer`,
`update_layers(required_tiles: Set[str])`), but `update()` — the only method actually called from the
per-tick loop in `carla_sim_consolidated.py:446` (`self.mesh_streamer.update()`) — did nothing. Every
tick this method ran and silently no-op'd.

Also verified a **correction to the original prompt's caveat**: the prompt said
`ENABLE_MESH_STREAMING` defaults to `False` ("low-stakes"). In this repo state, the actually-active
`Settings` class (confirmed via `SETTINGS.ENABLE_MESH_STREAMING` at runtime) has it set to **`True`**.
So this stub was live-by-default, not a rarely-hit dead path — raising the stakes above what the
original audit note implied.

Read `TileStreamer` (`ultimate_pipeline/carla_tools/tile_streamer.py`) in full: it is not redundant
with `MeshStreamer`. `TileStreamer.stream_once(ego_vehicle)` computes which OpenDRIVE **tile files**
should be active around the ego (bounding-box + adjacency-radius + optional FOV) and only **logs**
load/unload intentions (`_load_tile`/`_unload_tile` — explicitly "no CARLA map loading here").
`MeshStreamer` is the system that actually calls CARLA's `world.load_map_layer`/`unload_map_layer` for
the corresponding UE4 sublevels. They are complementary siblings, not duplicates — confirmed further by
the third sibling in the same tick loop, `ActorStreamManager.update(self.vehicle)`, which follows the
same "takes the vehicle/relevant-tile-state, does the real per-tick work" shape.

**Decision (implemented, option a):** Gave `update()` a `required_tiles: Optional[Set[str]] = None`
parameter and had it delegate to the already-correct `update_layers()` (`self.update_layers(required_tiles
or set())`) rather than duplicating `TileStreamer`'s bounding-box/adjacency tile-membership math inside
`MeshStreamer`. At the call site (`carla_sim_consolidated.py` `tick()`), `MeshStreamer.update()` is now
fed the sibling `TileStreamer`'s `loaded_tiles` (the field `stream_once()` actually keeps current every
tick — `required_tiles` on `TileStreamer` is only touched by the separate `load_tiles()` static
compatibility path, so it was not the right field to read):

```python
required_tiles = self.tile_streamer.loaded_tiles if self.tile_streamer else set()
self.mesh_streamer.update(required_tiles)
```

This keeps mesh layer streaming in sync with the same tile set `TileStreamer` already decided is
relevant, with no new tile-membership logic to maintain/drift from `TileStreamer`'s.

**Tests:** `tests/unit/test_mesh_streamer_update.py` (5 tests) — constructs `MeshStreamer` against a
fake `world` object (no live CARLA needed; `__init__` only requires `_CARLA_AVAILABLE` truthy + a world
exposing `load_map_layer`/`unload_map_layer`), and covers: loads layers for required tiles, unloads
layers no longer required, defaults to an empty set when called with no args (keeps `update()` safely
callable with zero args, matching the old call site's shape before I also updated the call site),
no-ops when `SETTINGS.ENABLE_MESH_STREAMING` is `False`, and delegates to `update_layers` (behavior
contract, not reimplementation).

## 2. `ultimate_pipeline/geometry/mesh_continuity_repairer.py:473-474` — `scan_for_discontinuities(self): pass`

**Verified the correction in the task dispatch myself, independently:** grepped the whole repo.
`ultimate_pipeline/dev_tools/tools/find_broken_roads.py` (the claimed caller from the *original* audit
note) does not exist anywhere under the canonical `ultimate_pipeline/` tree — `ultimate_pipeline/dev_tools/`
did not exist at all before this task. It only existed at
`submission/infrastructure/ultimate_pipeline/dev_tools/tools/find_broken_roads.py`, which I did not touch
(confirmed `submission/infrastructure/` is the archived/frozen donor tree per
`reports/opencode_batch_20260802/03B_CANONICAL_RELEASE_TREE_DECISION.md`). Grepping the canonical tree for
`scan_for_discontinuities` found **zero callers** besides the method's own definition — the corrected
disposition from the task dispatch is accurate.

Also verified `MeshContinuityRepairer` itself is **not** dead: it's actively constructed and used via
`scan_roads()` and `MeshContinuityRepairer.run()` in `ultimate_pipeline/pipeline_stages/stage_06_links.py`
(3 call sites) and `ultimate_pipeline/main_pipeline.py`. Only the one method, `scan_for_discontinuities`,
was dead.

**Decision (option b): created a real canonical-tree dev CLI, and redirected the stub to the corrected
checker instead of leaving it dead.**

- Created `ultimate_pipeline/dev_tools/tools/find_broken_roads.py` (plus `ultimate_pipeline/dev_tools/__init__.py`
  and `ultimate_pipeline/dev_tools/tools/__init__.py` — the subpackage didn't exist in the canonical tree
  at all). This is a real implementation, not a copy of the donor stub: it wires into
  `ultimate_pipeline.quality.check_geometric_continuity.check_geometric_continuity` (the C6-corrected,
  actively-maintained checker also used by Stage 6's `gate_geometric_continuity` quality gate — did not
  modify that file, only imported/called it, per the task boundary). Provides a `find_broken_roads(xodr_path,
  eps_xy, eps_hdg)` helper, an argparse CLI (`--json`, `--eps-xy`, `--eps-hdg`), and a `main(argv)` entry
  point usable both from the command line and from tests/other code.
- Redirected `MeshContinuityRepairer.scan_for_discontinuities()` to call the same corrected checker
  (`check_geometric_continuity(self.xodr_path)`) rather than either leaving it dead or implementing a
  second, parallel, hand-rolled continuity scanner that could diverge from the C6-corrected logic over
  time. Deliberately did **not** point it at this class's own `scan_roads()` — that method predates the C6
  fix, uses a naive chained x/y/hdg comparison (ignores `link_kind`/`contactPoint`), and per C6's own
  findings produced large numbers of false positives before the fix. Pointing both the new CLI and the
  redirected stub at the same corrected checker keeps exactly one source of truth for "is this road link
  broken."
- Rationale for redirecting rather than deleting the method entirely: `scan_for_discontinuities` reads as
  a natural, discoverable public API on this class (parallel to `scan_roads`), so turning it into a real,
  correct one-line delegator is more useful than removing it and is a smaller/safer diff than deletion
  would be for any future caller who reasonably expects a method with that name to exist on this class.

**Tests:** `tests/unit/test_find_broken_roads_cli.py` (7 tests) — builds minimal two-road `.xodr` fixtures
(continuous vs. a genuine 5 m gap, modeled on the existing fixture style in
`tests/unit/test_geometric_continuity_contactpoint.py`) and covers: CLI reports "no issues" on a continuous
map (exit 0), reports human-readable broken-link lines on a broken map (exit 1), `--json` mode emits a
parseable report dict, missing the required `xodr` positional exits 2 via argparse's standard
usage-to-stderr behavior, the `find_broken_roads()` helper returns the report dict directly, and
`MeshContinuityRepairer.scan_for_discontinuities()` now returns the same real report (for both the broken
and continuous fixtures) instead of `None`. (Note: the broken fixture reports `num_issues == 2`, not 1 —
correct behavior, since the gap is flagged from both directions: road 1's successor link to road 2, and
road 2's predecessor link back to road 1.)

## 3. `ultimate_pipeline/database/db_manager.py:302-303` — `_get_connection(self): pass`

**Verified:** `grep -rn "_get_connection" ultimate_pipeline/` (re-run myself) finds only the definition —
zero callers anywhere in the canonical tree. `Database._connect(self) -> sqlite3.Connection` (line 75,
`return sqlite3.connect(self.db_path, timeout=30)`) is the real, actively-used connection method, called
throughout the class (`_get_table_schema`, `_migrate_add_missing_columns`, `_ensure_tables`,
`log_dataset_entry`, `log_experiment`, `log_domain_gap_metric`, `log_pipeline_run`). `_get_connection` was
a redundant duplicate stub with no distinguishing docstring or usage pattern to derive intended behavior
from.

**Decision (removed):** Deleted the method outright — simplest option, nothing called it, nothing breaks,
and there was no basis (no caller, no docstring, no distinct naming convention elsewhere in the class) to
justify implementing a second, speculative connection mechanism.

**Tests:** `tests/unit/test_db_manager_get_connection_removed.py` (2 tests) — asserts
`hasattr(Database, "_get_connection")` is now `False` (locks in the removal), and a regression check that
`Database._connect()` still works end-to-end (constructs a `Database` against a temp DB path via
monkeypatched `SETTINGS.DB_FILE`, opens a connection, confirms the expected tables exist).

## Files changed

- `ultimate_pipeline/carla_tools/mesh_streamer.py` — implemented `update()`.
- `ultimate_pipeline/carla_tools/carla_sim_consolidated.py` — call site: pass `tile_streamer.loaded_tiles`
  into `mesh_streamer.update()`.
- `ultimate_pipeline/geometry/mesh_continuity_repairer.py` — redirected `scan_for_discontinuities()` to
  the C6-corrected checker.
- `ultimate_pipeline/dev_tools/__init__.py`, `ultimate_pipeline/dev_tools/tools/__init__.py`,
  `ultimate_pipeline/dev_tools/tools/find_broken_roads.py` — new real CLI (not a copy of the archived
  donor stub).
- `ultimate_pipeline/database/db_manager.py` — removed `_get_connection()`.
- New tests: `tests/unit/test_mesh_streamer_update.py`, `tests/unit/test_find_broken_roads_cli.py`,
  `tests/unit/test_db_manager_get_connection_removed.py`.

Did not touch: `ultimate_pipeline/core/carla_utils.py`, `ultimate_pipeline/quality/check_geometric_continuity.py`
(called into it only), anything under `submission/infrastructure/`.

## Verification

Full suite: `UP_DISABLE_CARLA=1 .venv/Scripts/python.exe -m pytest` from the worktree root —
**1071 passed, 1 skipped, 0 failed** (180.88s). The 1 skip pre-exists and is unrelated to this task.

## Verdict

`STUB_CLEANUP mesh_streamer=implemented continuity_repairer=redirected db_get_connection=removed`
