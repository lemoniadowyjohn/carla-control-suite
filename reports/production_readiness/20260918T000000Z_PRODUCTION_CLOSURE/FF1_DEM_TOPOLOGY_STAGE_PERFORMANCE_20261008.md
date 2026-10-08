# FF1 — Why the RQ1 trial takes ~8 hours: measured bottleneck

**Date**: 2026-10-08
**Scope**: performance only. No correctness claim is made or changed here.
**Starting point**: existing timing data in `reports/rq1_trial_runs_x2_verify/run_01/`, per instruction. No full-pipeline re-run was performed.

## Headline

Two corrections to the premise, both measured:

1. **It is not the DEM stage.** DEM/elevation took **~6 minutes**. The ~6 hours is
   stage `03_topology_repair`.
2. **It is not "just slow" — there is a genuine O(n²) algorithm.** The dominant
   cost is `MapPlotter.save_preview`, ~18.7 min per call, and inside it
   `_detect_overlaps` is a textbook quadratic pairwise loop.

Total run: **02:44:48 → 10:41:25 = 7h 56m 37s (28,597 s)**, matching the quoted 28,587 s.

## Measured timeline (from artifact mtimes, 76 files)

Derived from LastWriteTime of every file under the run directory. This is real
evidence, not inference.

| Window | Duration | What happened |
|---|---|---|
| 02:44:48–02:53:19 | 8m | sanitize, georeference, SUMO |
| 02:53:19–02:54:11 | <1m | `02_sumo_fixed.xodr` (132 MB) |
| 02:54:11–03:25:16 | 31m | sumo repair + `map_preview_03_topology_repair.png` |
| **03:25:16–09:11:05** | **5h 45m 49s** | **see "the unexplained stall"** |
| 09:11:05–09:12:27 | 1m 22s | junction_integrity gate + XODR validator convergence |
| 09:12:27–09:54:57 | 42m | continuity; wrote `stage6_containment_runtime.json` (**732 MB**) |
| **09:55–10:01:21** | **~6m** | **DEM / elevation — this is the stage the prompt suspected** |
| 10:02–10:39 | 37m | lanes stage |
| 10:40:28–10:41:25 | <1m | final XODR, then CARLA-FATAL lane connectivity |

10 `map_preview_*.png` renders occur in this run.

## Stage-03 sub-step timings, measured on the real 138.9 MB file

Run against `03_topology_20261008_024449_086823.xodr` (32,266 roads, 3,559 junctions),
in the order `stage_03_topology_repair.py` executes them:

| Sub-step | Time |
|---|---|
| `load_xodr` (ET.parse) | 8.8 s |
| `TopologyRepair.run` | 1.8 s |
| `save_xodr` (write 138 MB) | 24.7 s |
| `JunctionIntegrityGate.validate` | 10.3 s |
| **`MapPlotter.save_preview`** | **1121.1 s (18.7 min)** |

**So stage 3's real compute is ~46 seconds plus an 18.7-minute preview.**

### A hypothesis I disproved rather than reported

Artifact mtimes initially suggested `junction_integrity` owned the 5h46m gap, and
the stdout log's line ordering seemed to confirm it. That was wrong, twice over:
- The gate takes **10–12 s** measured directly on the real file.
- The log is **block-buffered** to a file, so line adjacency does not imply
  temporal adjacency. Log-adjacency reasoning about this stage is unsound.

`check_junction_integrity.py` was also inspected for algorithmic problems: it is
all O(n) / O(n·m) with set lookups and no quadratic path. It is not the problem.

## The actual bottleneck: `_detect_overlaps` is O(n²)

`ultimate_pipeline/visualization/map_plotter.py:186-233`. Its docstring claims
"Efficiently detect overlapping roads using pre-calculated bounding boxes and
numpy", and it does precompute per-road bounding boxes — but then compares
**every road against every other road** in a pure-Python double loop:

```python
for i in range(len(p_roads)):
    for j in range(i + 1, len(p_roads)):
```

The bounding-box test is only an early-out *inside* the loop; it does not reduce
the iteration count. At 32,266 roads that is **5.21 × 10⁸ pairs** of Python-level
loop overhead.

cProfile attributed **575.6 s tottime / 582.8 s cumtime** to this one function
(41 % of `save_preview`). cProfile overhead inflated the total to 1390 s vs the
clean 1121 s, so the honest figure for `_detect_overlaps` is the ~575 s from the
profile, not the inflated total.

### Quadratic scaling demonstrated on synthetic input

Per instruction, synthetic and bounded — no pinned map involved:

| roads | pairs | seconds | µs/pair | ratio vs previous |
|---|---|---|---|---|
| 500 | 124,750 | 0.125 | 1.000 | — |
| 1000 | 499,500 | 0.418 | 0.836 | ×3.35 |
| 2000 | 1,999,000 | 1.892 | 0.947 | ×4.53 |
| 4000 | 7,998,000 | 7.111 | 0.889 | ×3.76 |
| 8000 | 31,996,000 | 24.002 | 0.750 | ×3.38 |

≈4× time per 2× N at a flat ~0.75–1.0 µs/pair: textbook quadratic, cost
dominated by interpreter overhead rather than the numpy work.
Extrapolated to 32,266 roads: **~390 s (~6.5 min)** per preview, consistent with
the 575 s observed on the denser real map.

### The rest of the preview cost is also avoidable

`_draw_direction_arrow` is invoked **31,577 times** for one preview
(`map_plotter.py:120`), costing 377.8 s cumulative. Each call adds an individual
matplotlib `Patch`, and matplotlib then spends 348 s in `_update_patch_limits`
and 122 s in `split_bezier_intersecting_with_closedpath` doing per-patch clipping
and Bézier splitting. 31,577 individually-clipped patches is the wrong data
structure for 32k roads; a single `LineCollection` would collapse this.

## The unexplained stall — stated, not papered over

**5h 45m 49s (03:25:16 → 09:11:05) is still not fully accounted for.** I inspected
every code path in that window — `stage_03_topology_repair.py`,
`_stage_gate` (`main_pipeline.py:3323`), `gate_junction_integrity`
(`quality_gate_manager.py:292`), the `save_preview` exception wrapper
(`main_pipeline.py:661`) — and measured each in isolation. None of them can consume
5h46m: `_stage_gate` is a print plus a runner call plus a JSON write, and the
preview wrapper only catches exceptions (no retry loop, no timeout, no lock).

Two candidate explanations remain, and I did **not** prove either:
- **External contention.** This is a heavily shared machine — dozens of registered
  worktrees, multiple concurrent agents, and a live RQ1 trial during the window.
  A ~17× discrepancy between measured work and wall time is what starvation looks
  like.
- **An unlogged step** whose artifacts I could not attribute.

I am flagging this as open rather than attributing it. Note that 10 previews ×
18.7 min ≈ **3.1 hours** of the 7.9 h is already explained by the quadratic path
alone, so fixing `_detect_overlaps` is necessary but may not be sufficient.

## What this means for a real N=5 RQ1 trial

At the observed 7.9 h/run, N=5 is ~40 h, as stated. But the cost is not inherent
to the workload:

- The RQ1 determinism question is about **pipeline determinism**, not map rendering.
  Ten diagnostic PNG previews are observability, not measurement.
- `_detect_overlaps` is a pure visualization concern with no bearing on any
  determinism gate.
- Therefore the highest-leverage change is likely a **preview skip/sampling
  switch for trial mode** (e.g. render previews at most once, or sample roads),
  which would remove ~3.1 h per run immediately. A spatial index (STRtree or a
  uniform grid) over `_detect_overlaps` would take it from ~390 s to near-linear.

Neither is implemented here — FF1 asked for measurement, not a fix.

## Reproduction

All measurements are from single bounded invocations on the existing run
directory; no pipeline stage was re-run and no map pin was touched.

- `python` + `xml.etree.ElementTree` on the real 138.9 MB stage file
- `cProfile` around `MapPlotter.save_preview` (cross-checked against an unprofiled run)
- synthetic `_detect_overlaps` scaling ladder, 500→8000 roads