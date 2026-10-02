# Phase 2: OSM2World `--center` Support + Full Re-cook

**Branch**: `feat/osm2world-center-support`
**Base**: `fix/p0-coordinate-frame-tile-placement-authority-20261001` (SHA `9a9fa764`)
**Goal**: Achieve `PASS` on `true_placement_verification.py` at 10m tolerance

---

## Acceptance Criteria

| Check | Target |
|-------|--------|
| `true_placement_verification.py` | `PASS` at 10m tolerance |
| Max p95 residual | ≤ 10m across all 20 tiles |
| Median p95 residual | ≤ 5m |
| All 20 tiles | `VERIFIED` status |
| Roundtrip QA | All `ROUNDTRIP_PASS` |
| Pinned map SHA | Unchanged (`370abbbb...`) |

---

## Work Items

### 1. OSM2World Upgrade (2-3 hours)
- [ ] Find OSM2World version with `--center` support
  - Check: `java -jar OSM2World.jar convert --help | grep center`
  - Sources: GitHub releases, OSM2World repo `main` branch, or build from source
- [ ] Build from source if needed (Maven, Java 17+)
- [ ] Validate config compatibility (existing `.properties` files)
- [ ] Replace `carla_governed/OSM2World-latest-bin/OSM2World.jar` + `lib/` deps
- [ ] Smoke test: `java -jar OSM2World.jar convert -i test.osm -o test.obj --center <lat> <lon>`

### 2. Update Pipeline for `--center` Flag (30 min)
- [ ] Modify `ultimate_pipeline/enrichment/osm2world_runner.py`:
  - Add `center` parameter to `_run_osm2world_for_output`
  - Pass `--center <lat> <lon>` when provided
  - Compute center from tile's source OSM bbox center (WGS84)
- [ ] Modify `ultimate_pipeline/tiling/tile_fbx_generator.py`:
  - Pass `center` to `OSM2WorldRunner` in `generate_tile_fbx`
  - Center = tile's source OSM bbox center in WGS84

### 3. Full 20-Tile Re-cook (10 min)
- [ ] Delete old cook artifacts
- [ ] Run: `$env:OSM2WORLD_HOME = "new_path"; $env:ENABLE_OSM2WORLD = "1"; python -m scripts.cook_full_grid_tiles --verbose`
- [ ] Verify all 20 tiles `OK` + `ROUNDTRIP_PASS`

### 3. Re-verify True Placement (2 min)
- [ ] Recompute placement manifests for new artifacts
- [ ] Run: `python tools/true_placement_verification.py --cook-results <new_cook> --out <out>`
- [ ] Confirm `PASS` at 10m tolerance

### 4. Evidence Update (15 min)
- [ ] Update `TILE_PLACEMENT_BEFORE_AFTER.json` with new results
- [ ] Update `TRUE_PLACEMENT_VERIFICATION.json` showing PASS
- [ ] Update `FINAL_VERDICT.json` → `PASS`
- [ ] Commit + push to `feat/osm2world-center-support`

---

## Rollback Plan

If any regression:
```bash
git checkout fix/p0-coordinate-frame-tile-placement-authority-20261001 -- carla_governed/OSM2World-latest-bin/
# Re-cook with old JAR if needed
```

---

## Dependencies

| Tool | Version |
|------|---------|
| Java | 17+ (Temurin) |
| Maven | 3.8+ |
| OSM2World source | GitHub `master` or tagged release with `--center` |

---

## Timeline

| Day | Activity |
|-----|----------|
| 1 | OSM2World upgrade + pipeline integration |
| 2 | Full re-cook + verification + evidence update |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| OSM2World regression (other features) | Medium | High | Smoke test all config options; keep old JAR for rollback |
| Config incompatibility | Low | Medium | Compare `.properties` schema |
| Re-cook fails on dense tiles | Low | Medium | OSM duplicate tag fix already in place |

---

## Success Definition

**Phase 2 complete when:**
1. `true_placement_verification.py` returns `{"status": "PASS", "max_p95_residual_m": ≤ 10.0}`
2. All 20 tiles `VERIFIED` with p95 ≤ 10m
3. `FINAL_VERDICT.json` reads `"verdict": "PASS"`
4. Branch `feat/osm2world-center-support` pushed and PR opened

---

## Out of Scope

- OSM2World feature development (upstream)
- CARLA runtime import test (separate workstream)
- Larger map support (beyond 20 tiles)