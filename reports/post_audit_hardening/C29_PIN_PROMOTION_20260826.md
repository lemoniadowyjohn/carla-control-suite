# C29 pin promotion (2026-08-26) — building-frame-patched candidate is now the auto map of record

User decision: promote the surgically-patched candidate from
`C29_PINNED_MAP_BUILDING_PATCH_APPLIED.md` to be the live `auto_map_of_record` pin.

## What changed
`ultimate_pipeline/carla_tools/map_registry.py::PINNED_MAP_REGISTRY["auto_map_of_record"]`
(and its byte-identical mirror `submission/infrastructure/ultimate_pipeline/carla_tools/
map_registry.py` — the two are kept in sync, confirmed identical before and after this edit):

| | before | after |
|---|---|---|
| path | `.../candidate/ingolstadt_perception_map_of_record_20260819_160350.xodr` | `.../candidate/ingolstadt_perception_map_of_record_20260819_160350_C29_BUILDING_PATCH.xodr` |
| sha256 | `69b1f52016ebdc3e643616f86161d85789624c94d48e5caf56c53004d534de6e` | `744757f3f01da835269b5678eeb269cf5d534984213c551b9c475699aa73aec8` |
| bytes | 144,142,210 | 144,385,542 |

`verify_pinned_map("auto_map_of_record")` — the fail-closed, content-addressed drift guard
that is the actual single source of truth any code in this repo uses to resolve "the" auto
map — now resolves to the corrected file. Nothing else in the registry changed (manual
Grid0828 entry, alias table, drift-guard logic all untouched).

## What did NOT change
- **The pre-patch file is not deleted.** It remains committed in git/LFS at its original
  path/sha for provenance and rollback; only the registry *pointer* moved. Anyone resolving
  the old sha256 directly (e.g. existing RQ1/C19/C24/C26 provenance JSONs that cite
  `69b1f520...`) still gets the exact file those analyses were actually run against — those
  records are accurate historical statements and were deliberately NOT rewritten.
- **Road/lane/signal/elevation data is identical** between the two pins — this promotion
  only affects where buildings render (see `C29_PINNED_MAP_BUILDING_PATCH_APPLIED.md` for
  the full structural diff proving this).
- No currently-live pipeline code called `verify_pinned_map("auto_map_of_record")` before
  this change (grep-confirmed across `ultimate_pipeline/` and `scripts/` — zero call sites
  besides the registry module itself and its test) — so this promotion has zero blast
  radius on the running pipeline today. It takes effect for whatever future code (e.g. RQ2
  capture tooling) resolves the pin through this registry.

## Verification
- TDD order preserved: updated `tests/unit/test_map_registry_pinning.py`'s
  `test_real_auto_map_of_record_matches_pinned_sha256` to expect the new sha256 FIRST
  (confirmed RED — file/registry still pointed at the old pin), then updated the registry
  (confirmed GREEN, 10/10 in that file).
- Full unit suite: see commit for exact pass count (0 regressions expected — same pattern as
  every other change this session).
- The new pinned file was force-added to git (`git add -f`, overriding the general
  `campaigns/*/candidate/` ignore rule — the same exception mechanism the original pin used)
  and confirmed to go through the LFS clean filter (index entry is a real LFS pointer, oid
  matches the file's sha256 exactly), not committed as a raw 144MB blob.

## Not done in this pass, flagged not assumed
- The old pinned file (`69b1f520...`) is still tracked in git/LFS, using ~144MB of
  additional LFS storage now that a second full map is also tracked. Removing it is a
  separate, optional cleanup decision — not taken here since it's a destructive action
  beyond what "promote" required.
- Downstream artifacts computed against the OLD pin (RQ1 structural gap, C19 thesis
  assembly, C24 curvature metric, C26 local-registration hardening) are unaffected in
  substance (all road-network-based, not building-based) and were not re-run or edited.
