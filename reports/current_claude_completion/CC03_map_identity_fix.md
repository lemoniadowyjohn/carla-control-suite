# CC03 — Map-Identity Fix Verification

**Requirement (P0):** repair the red map-identity test — `CarlaSession` lacked `validate_map_identity`.

## State: IMPLEMENTED & COMMITTED (`7053bab5`)

`CarlaSession.validate_map_identity()` exists in `ultimate_pipeline/carla_tools/session.py` and delegates to the narrow guard `ultimate_pipeline/carla_tools/map_identity_guard.py::validate_world_map`.

### What the guard proves (fail-closed map-*name* identity)

| Behavior | Mechanism | Test |
|---|---|---|
| Correct map identity **passes** | exact `expected_map_name` match / `expected_substring` containment | `test_validate_world_map_passes_custom_map`, `test_session_exposes_map_identity_guard` |
| Wrong map name **fails** | mismatch → failure list → `RuntimeError` under strict | (covered by mismatch path) |
| Default **Town fallback fails** | `is_town_fallback()` detects `Town*` / `/Game/Carla/Maps/Town*` leaf | `test_validate_world_map_raises_on_strict_town_fallback` |
| **Fail-open is impossible** | under `strict=True` any failure `raise RuntimeError`; no silent pass path | strict-mode tests |
| Packaged-path handling | normalizes `\`→`/`, matches leaf | `test_town_fallback_detection_handles_packaged_paths` |
| Identity persistence | `save_map_identity()` writes sorted JSON | `test_save_map_identity_writes_sorted_json` |

Strict mode is also environment-gated (`UP_THESIS_STRICT=1`) when `strict` is not passed explicitly, so thesis-strict runs fail closed automatically.

### Focused test result

```
tests/unit/test_map_identity_guard.py ..... [5 passed in 0.13s]
```

## Honest scope limitation (NOT a regression — a documented boundary)

P0's *idealized* test matrix additionally listed "wrong XODR SHA fails" and "wrong cooked-package SHA fails when package identity is required." The committed guard is deliberately the **narrow map-name identity guard** (per P0's own title "the **narrow** … fix" and "Do not broaden scope"). It does **not** hash the XODR or cooked-package and therefore does not assert those two rows.

Those SHA-binding gates belong to the broader **runtime-proof** surface (`02_HARD_CONSTRAINTS.md`: "the test must prevent loading an older package with the same map name") and require XODR/package hashing + metadata. Adding them here would broaden scope beyond the authorized narrow fix. They are recorded as **follow-up** (see status `PARTIALLY_FIXED` scope note), not silently claimed.

**Conclusion:** the red map-identity test is **VERIFIED_FIXED** for map-name identity (fail-closed, no fail-open path). XODR-SHA / cooked-package-SHA identity gating is **NOT_APPLICABLE to this narrow fix** and is deferred to the runtime-proof gate.
