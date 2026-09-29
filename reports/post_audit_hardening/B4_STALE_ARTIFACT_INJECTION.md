# B4 — STALE-ARTIFACT INJECTION TEST REPORT

- Date: 2026-09-24
- Test: `tests/quality/test_stale_artifact_injection.py` (20 tests)
- Run: `.venv\Scripts\python.exe -m pytest tests/quality/test_stale_artifact_injection.py -p no:cacheprovider` → **20 passed**
- Scope: prove downstream cook/import tooling cannot silently consume an old map after a newer map is registered.

## 1. Temp environment

Two maps A (stale) and B (registered), distinct sha256 (`_sha256_bytes`), pin registry
`auto_map_of_record -> B` with `sha256/bytes/role/frame/aliases/rebase_dx/dy` matching
`validate_registry_entry`'s schema (`map_registry.py:454`). Stale A is planted in every
plausible discovery directory (same dir, a `run_stale/` sibling, and as an
`08_final*.xodr`-family file) and given a **newer mtime** (2.0E9 vs 1.0E9) so any
newest-by-mtime selection would pick A over B. `verify_pinned_map` is exercised with
`base_dir=` and `registry=` overrides so no real artifact is touched.

## 2. Governed paths: B exclusively (PASS)

| Consumer | Entry point | Outcome |
| --- | --- | --- |
| Map-of-record resolver | `verify_pinned_map` (`carla_tools/map_registry.py:935`) | resolves to B via canonical key and alias; `verification_status=VERIFIED`, `registry_sha256` present |
| Content drift | `MapRegistryDriftError` on tampered B | fail-closed even with newer stale A present |
| Byte-size drift | `MapRegistryDriftError` on truncated B | fail-closed |
| Missing registered file | `MapRegistryDriftError` | fail-closed despite newer stale A |
| Unregistered basename | `LookupError` for A by exact filename | no basename guessing |
| Cook offset source | registry receipt frame fields / `_header_offset_from_registry` contract | never derived from newest file |
| Import staging | `stage_large_map_package` (`tiling/large_map_package.py:286`) | stagges B, refuses A against B sha (`xodr sha256 mismatch`) |
| Post-stage validation | `validate_staged_package` (`large_map_package.py:578`) | PASS for B; FAIL when staged XODR swapped to A |
| Tile FBX provenance gate | `_tile_provenance_status` (`large_map_package.py:263`) | stale-generation tile -> `mismatch`; matching -> `ok`; no manifest -> `missing_manifest`; no sha -> `missing_sha` |

Conclusions: every registry-governed consumer is content-addressed, never
mtime/glob/basename/order driven; all drift paths fail closed.

## 3. Demonstrated NON-governed stale-selection paths (regression-pinned)

Both still select newest-by-mtime when structural repair evidence is absent — i.e. the
exact GAP-012 defect class the governed paths exist to prevent. Tests encode current
behavior so a fix removing the mtime tie-break updates them deliberately.

1. `ultimate_pipeline/config/settings.py::_resolve_input_xodr_with_fallback` (181-244):
   next pipeline input. Stale A (newer mtime, no repair sibling) wins over B in a
   sibling run dir — pinned by
   `test_next_run_input_is_stale_by_mtime_without_repair_evidence`.
   With a `_laneSectionFixed` sibling present, the structural guard (239) outranks
   mtime — pinned by `test_next_run_input_prefers_repair_evidence_over_mtime`.
2. `ultimate_pipeline/tools/artifact_locator.py::_newest_final_xodr` (82-124):
   same semantics for the tool-side latest-file lookup — pinned by
   `test_artifact_locator_is_stale_by_mtime_without_repair_evidence` /
   `test_artifact_locator_prefers_repair_evidence_over_mtime`.
3. `resolve_run_dir` (`artifact_locator.py:22`) is explicit-only (env/arg, `.` fallback,
   no mtime authority) — pinned by `test_resolve_run_dir_is_explicit_not_mtime`.

## 4. Newly demonstrated compile-time defect

`scripts/cook_full_grid_tiles.py` **cannot be imported today**:

```
File "scripts/cook_full_grid_tiles.py", line 96, in <module>
    HEADER_OFFSET_XY = _header_offset_from_registry(_pinned)
ValueError: Registry entry 'auto_map_of_record' is missing structured frame fields
'rebase_dx' / 'rebase_dy' ...
```

Root cause: `verify_pinned_map` (map_registry.py:1018-1036) returns a receipt that omits
the normalized structured frame fields (`frame_id`, `frame_kind`, `crs_authority`,
`rebase_dx`, `rebase_dy`, `frame_status`) even though `validate_registry_entry` already
computed them (`norm`, lines 542-563). `_header_offset_from_registry` (cook:69-91) reads
them from the receipt. Failure is **fail-closed** (never silent, never falls back to the
newest file), so safety holds — but the entire full-grid-tile cook is blocked.

Bounded fix (proposed, not applied on this pass): in `verify_pinned_map`, copy the
structured frame fields from `norm` into the returned receipt. Additive to any consumer;
the cook contract then resolves and stays registry-bound. Regression coverage already
holds both outcomes: `TestCookOffsetAuthority::test_offset_source_is_registry_bound_or_fails_closed`
asserts the offset equals the registry binding when the fields are present, or the cook
contract raises ValueError when they are absent.

## 5. Selection mechanisms audited

| Mechanism | Status |
| --- | --- |
| newest mtime selection | governed paths: none; settings.py / artifact_locator still mtime-tiebreak (pinned, §3) |
| glob ordering / basename guessing | governed paths: none (verified: unregistered filename raises LookupError) |
| directory order / lexicographic sort | governed paths: none; `run_full_domain_gap.py:3397` etc. are separate consumers reported in B3 |
| registry path + sha256 | sole authority for map-of-record, cook, import staging, tile provenance |

Test artifact: `tests/quality/test_stale_artifact_injection.py` (sha256
`9e2deb418cc68d10571409144689cf14393b98d371e24ca6721dd3102b4b9de4`), no production code changed.