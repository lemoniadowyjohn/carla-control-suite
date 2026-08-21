# C22 (LOW-MED) — dead/no-op stub cleanup (judgment call per stub)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: `fix/post-audit-phase-e-junctions-roundabouts-20260803` · Interp: `./.venv/Scripts/python.exe` · UP_DISABLE_CARLA=1
Rules: TDD for any implemented logic; full-suite green; **EXPLICIT-PATHSPEC commit**.
**Model: Sonnet, reasoning effort high.** Fully offline. Independent of C21 (no file overlap) and of the
concurrent CARLA/TDR work (does not touch `carla_utils.py`).

## Why this task, and why Sonnet
A repo-wide AST scan for function bodies that are literally just `pass` or `raise NotImplementedError`
found 3 real, reachable stubs (full list, with false positives already ruled out, in the audit below). None
of them are large or mechanical — each needs a **judgment call** (implement vs. formally deprecate/remove vs.
leave as documented no-op) informed by reading the surrounding class and its actual callers, which is a better
fit for careful synthesis at high effort than for a long autonomous xhigh run.

## Audit (already done — verify before changing, don't re-discover)
Found via: `ast.walk` over every `FunctionDef`/`AsyncFunctionDef` in `ultimate_pipeline/`, filtering to bodies
that are exactly one `pass` or one `raise NotImplementedError(...)` statement (docstring-only bodies excluded).
8 hits total; 5 are legitimate (Click CLI group functions in `cli.py`, and `visualization/map_plotter.py`'s
`_draw_lane_boundaries` which has an explicit "intentionally disabled" docstring) — do not touch those 5.

The 3 real ones:

1. **`ultimate_pipeline/carla_tools/mesh_streamer.py:115` — `MeshStreamer.update(self): pass`**
   Called with no arguments from `ultimate_pipeline/carla_tools/carla_sim_consolidated.py:446`
   (`self.mesh_streamer.update()`) inside the interactive pygame simulator's per-tick loop. The sibling
   system in the same loop, `TileStreamer`, is passed `self.vehicle` and does real work
   (`self.tile_streamer.stream_once(self.vehicle)`); `MeshStreamer` has real logic already
   (`load_layer`/`unload_layer`/`update_layers(required_tiles)`) but `update()` never calls any of it.
   **Caveat:** `MeshStreamer.enabled` defaults to `SETTINGS.ENABLE_MESH_STREAMING` which is `False` by
   default, and this whole file is a manual/interactive debug tool, not part of the automated RQ1-RQ5
   pipeline — this is real but low-stakes.
2. **`ultimate_pipeline/geometry/mesh_continuity_repairer.py:473` — `scan_for_discontinuities(self): pass`**
   Called by `ultimate_pipeline/dev_tools/tools/find_broken_roads.py:10`
   (`broken = repairer.scan_for_discontinuities()`) — a standalone dev CLI tool. Always returns `None`, so
   that tool is silently broken (whatever iterates `broken` afterward gets `None`, not a list). **Caveat:**
   this class predates C6's continuity-checker fix (`ultimate_pipeline/quality/check_geometric_continuity.py`)
   — check whether `mesh_continuity_repairer.py` is legacy/superseded by the C6-corrected checker before
   investing in a real implementation; it may be more honest to point the dev tool at the real checker
   instead of implementing a second, parallel continuity scanner.
3. **`ultimate_pipeline/database/db_manager.py:302` — `_get_connection(self): pass`**
   Zero callers anywhere in the codebase (verified: `grep -rn "_get_connection" ultimate_pipeline/` finds only
   its own definition). Genuinely dead code — do not guess at intended behavior and implement something
   speculative.

## Steps
1. **`MeshStreamer.update()`:** either (a) wire it to call `self.update_layers(required_tiles)` with a
   sensible required-tile computation (mirror `TileStreamer`'s pattern — take the vehicle/ego position as a
   parameter, matching the sibling call site's `self.vehicle` argument; you'll need to add the parameter to
   the call site too), with tests mocking `self.world.load_map_layer`/`unload_map_layer` (no live CARLA), or
   (b) if you determine after reading `TileStreamer` that `MeshStreamer` is genuinely redundant with it
   (both appear to do layer-based streaming around the ego), document that finding and either remove
   `MeshStreamer` + its call site or leave a clear `# not implemented, see TileStreamer` note — your call,
   but justify it in the report either way.
2. **`scan_for_discontinuities()`:** determine whether `mesh_continuity_repairer.py` is dead/superseded
   (check git history + whether anything besides `find_broken_roads.py` references the class) or still
   meaningfully used. If superseded: point `find_broken_roads.py` at
   `ultimate_pipeline.quality.check_geometric_continuity.check_geometric_continuity` instead (the corrected,
   actively-maintained checker) rather than implementing a second one. If genuinely still needed as a
   lighter-weight standalone scan: implement it for real, with a test.
3. **`_get_connection()`:** since it's dead code with zero callers, the honest options are (a) remove it
   entirely (simplest — nothing calls it, nothing breaks), or (b) if `db_manager.py`'s class clearly implies
   what a connection getter should do (check the rest of the class for a `conn = ...` pattern used elsewhere
   that this should have factored out), implement it for real. Do not implement a guessed connection
   mechanism (e.g. inventing a DB driver/connection string) with no caller to validate it against — prefer
   removal if the intent isn't clear from context.

## Boundaries
- Do not touch `ultimate_pipeline/core/carla_utils.py` (concurrent GPU/TDR work owns it).
- Do not touch anything under `ultimate_pipeline/quality/check_geometric_continuity.py` itself (C6's file) —
  you may call it from `find_broken_roads.py`, not modify it.
- These are all small, independent changes — one commit per stub is fine, or one combined commit; your call,
  but keep the three changes logically separable in the commit message either way.
- If you determine any of the 3 genuinely isn't worth fixing (e.g. `MeshStreamer` truly is dead/superseded
  and removing it is out of scope for a "LOW-MED" task), it's fine to leave it and say so in the report —
  this task is about resolving the *ambiguity*, not forcing an implementation where none is warranted.

## Deliverables / verdict
- Resolution for each of the 3 stubs (implemented / removed / documented-as-intentional-noop), with tests for
  anything implemented.
- `reports/post_audit_hardening/C22_STUB_CLEANUP.md`: what you found for each, what you decided, and why.
- Push (explicit pathspec); local==remote; full suite green.
- **Verdict:** `STUB_CLEANUP mesh_streamer=<implemented|removed|noop> continuity_repairer=<implemented|redirected|noop> db_get_connection=<implemented|removed>` | PARTIAL.
