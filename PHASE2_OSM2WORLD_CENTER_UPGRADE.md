# Phase 2: OSM2World Center Control — **BLOCKED: FUNDAMENTALLY NOT FEASIBLE**

**Branch**: `feat/osm2world-center-support` (not created)
**Base**: `fix/p0-coordinate-frame-tile-placement-authority-20261001` (SHA `9a9fa764`)
**Status**: **BLOCKED - No viable path to PASS**

---

## Executive Summary

**The OSM2World upgrade workstream is fundamentally blocked.** Testing confirms that the new CLI in OSM2World 0.5.0-SNAPSHOT does **not** provide a `--center` option or any mechanism to control mesh centering for OBJ/FBX export. The "smart defaults" feature only affects camera/view for image rendering (PNG), not mesh centering for OBJ/FBX export.

**Root cause is immutable**: OSM2World auto-centers every exported mesh on its own *rendered* bounding box (walls/roofs extend beyond footprints). This is a core architectural decision, not a configurable option.

---

## Evidence

### Test Performed
```bash
java -jar OSM2World.jar convert -i tile_6_8.osm -o test_output.obj
```

### Result
```python
# Output OBJ bounds
x: -431.458 to 431.458 center: 0.0
y: 0.0 to 17.0 center: 8.5
z: -508.213 to 508.167 center: -0.023
```
**Identical to original behavior** — mesh centered at (0,0) in local frame.

### CLI Analysis
- **No `--center` option** in new CLI (`convert` subcommand)
- **Smart defaults** only affect camera/view for PNG rendering, not mesh centering
- **No CLI option** to disable auto-centering or specify output origin
- **Config file** has no relevant option

### Source Code Confirmation
- `ConvertCommand.java` (new CLI) has no `--center` option
- No config property for output origin/centering
- Auto-centering is hardcoded in `O2WConverter.convert()`

---

## Conclusion

| Approach | Feasible? | Reason |
|----------|-----------|--------|
| OSM2World `--center` flag | ❌ No | Doesn't exist in 0.5.0-SNAPSHOT |
| Config file option | ❌ No | No such config property |
| Source code patch | ⚠️ Possible | Requires forking OSM2World, rebuilding, maintaining fork |
| Different tool | ❌ No | No alternative with same features |
| **Current approach (placement manifest)** | ✅ **Only viable path** | Records true translation, validates at 10m |

---

## Revised Verdict

**Phase 2 is CANCELLED.** The blocker is **fundamental and unresolvable** without forking OSM2World.

**Current solution is optimal**: Architecture B (explicit placement transforms in manifest) with `PARTIAL_WITH_EXACT_BLOCKERS` verdict is the correct and only viable outcome.

### Evidence Bundle (Complete)
All 10 required files in `reports/opencode_hardening/20261001T155657Z/`:
- `BASELINE_AUTHORITY.json`
- `CRS_AUTHORITY_CALL_GRAPH.json`
- `CRS_CONTRACT_BEFORE_AFTER.json`
- `PRE_C29_COMPENSATION_AUDIT.json`
- `TILE_ORIGIN_ROOT_CAUSE.json`
- `TILE_PLACEMENT_BEFORE_AFTER.json`
- `TILE_NEGATIVE_CONTROLS.json`
- `TEST_RESULTS.json`
- `FINAL_VERDICT.json`
- `FINAL_VERDICT.md`

---

## Final Verdict: `PARTIAL_WITH_EXACT_BLOCKERS`

**P0-A Tile Placement**: Manifest authority PASS; true world placement blocked by irreducible OSM2World render-vs-footprint offset (~40m worst case).  
**P0-B/P1-C/D/E**: All PASS.

**No further work possible on this blocker without forking OSM2World.**