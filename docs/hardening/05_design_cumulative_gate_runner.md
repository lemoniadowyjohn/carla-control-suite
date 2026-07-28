# Design: Cumulative Gate Runner

## Purpose

Replace the current ad-hoc `_stage_gate()` calls scattered through `main_pipeline.py` with a **tally-all, fail-at-end** cumulative gate runner. This ensures every gate is evaluated even if earlier gates fail, producing a complete failure report rather than failing on the first violation.

## Current Problem

Each `_stage_gate()` call raises `RuntimeError` immediately on failure (when strict mode is active):

```python
# main_pipeline.py (current)
self._stage_gate("03_topology_repair", "junction_integrity", lambda: ...)
self._stage_gate("06_continuity", "geometric_continuity", lambda: ...)
self._stage_gate("05_elevation", "elevation_variance", lambda: ...)
# ...etc
```

If gate 1 fails, gates 2-10 never run → incomplete failure report.

## Design

### Centralized Runner

```python
# contracts/gate_runner.py

@dataclass
class GateResult:
    stage: str
    gate: str
    ok: bool
    detail: dict
    elapsed_s: float

class CumulativeGateRunner:
    def __init__(self, strict: bool = False):
        self.results: list[GateResult] = []
        self.strict = strict

    def run(self, stage: str, gate: str, fn: Callable) -> dict:
        t0 = time.time()
        try:
            report = fn()  # must return dict with "ok" key
            ok = bool(report.get("ok", False))
            elapsed = time.time() - t0
            self.results.append(GateResult(stage, gate, ok, report, elapsed))
            return report
        except Exception as e:
            elapsed = time.time() - t0
            fail = {"ok": False, "error": str(e)}
            self.results.append(GateResult(stage, gate, False, fail, elapsed))
            return fail

    def finalize(self) -> dict:
        failed = [r for r in self.results if not r.ok]
        if self.strict and failed:
            summary = "\n".join(
                f"  ❌ {r.stage}/{r.gate}: {r.detail}"
                for r in failed
            )
            raise RuntimeError(
                f"Cumulative gate runner: {len(failed)}/{len(self.results)} gates failed\n{summary}"
            )
        return {
            "total": len(self.results),
            "passed": len(self.results) - len(failed),
            "failed": len(failed),
            "results": [asdict(r) for r in self.results],
        }
```

### Integration in main_pipeline.py

Replace ad-hoc calls:

```python
# Before run_internal()
self._gates = CumulativeGateRunner(
    strict=resolve_strict_quality_gates(...)
)

# Each stage
self._gates.run("03", "junction_integrity", lambda: self.qgate.gate_junction_integrity(...))
self._gates.run("06", "geometric_continuity", lambda: ...)
# ...etc

# After all stages, once:
gate_summary = self._gates.finalize()  # may raise RuntimeError with ALL failures
```

### Gate Registry

| Gate ID | Stage | Runs After | Type |
|---|---|---|---|
| `xml_integrity` | 01 | sanitize | structural |
| `junction_integrity` | 03 | topology repair | structural |
| `geometric_continuity` | 06 | planView | geometric |
| `elevation_variance` | 05 | DEM | elevation |
| `elevation_stddev` | 05 | DEM | elevation |
| `elevation_smoothness` | 05 | DEM | elevation |
| `elevation_continuity` | 05 | DEM | elevation |
| `dem_full_coverage` | 05 | DEM | elevation |
| `lane_width_continuity` | 07 | lanes | lane |
| `lane_geometry_continuity` | 07 | lanes | lane |
| `origin_sanity` | 08 | final integrity | structural |
| `elevation_seams` | 08 | final integrity | elevation |
| `planview_seams_tiles` | 09 | tiling | geometric |
| `geometric_continuity_tiles` | 09 | tiling | geometric |
| `post_tiling_integrity` | 09 | tiling | structural |
| `drivable_surface` | 08G | hole scan (new) | drivability |

### Benefits

1. **Complete failure report**: All gates run, even if earlier ones fail
2. **Deterministic ordering**: Same sequence every run
3. **Metrics**: Each gate records elapsed time → performance regression detection
4. **Artifact**: Full JSON report written to output dir for thesis evidence
5. **Strict mode**: Still fail-closed, but with complete context

### Implementation Priority

1. Create `contracts/gate_runner.py` with `CumulativeGateRunner` class
2. Replace all `_stage_gate()` calls in `main_pipeline.py` (16 call sites)
3. Wire strict mode from `resolve_strict_quality_gates()`
4. Write `cumulative_gate_report.json` to `out_dir`
5. Add toggle: `UP_ENABLE_CUMULATIVE_GATES` (default True, fallback to legacy behavior)
