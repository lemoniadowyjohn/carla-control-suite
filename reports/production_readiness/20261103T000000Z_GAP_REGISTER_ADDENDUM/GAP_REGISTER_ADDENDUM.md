# GAP Register Addendum -- Post-PR16 Remediation (2026-10-23 .. 2026-11-03)

Machine-readable version: `GAP_REGISTER_ADDENDUM.json`.

This addendum continues the id sequence from the highest id in the existing
registers (`GAP-055`, see
`reports/production_readiness/20260918T000000Z_PRODUCTION_CLOSURE/MASTER_GAP_REGISTER.json`
and `.../20260919T000000Z_PRODUCTION_CLOSURE/MASTER_GAP_REGISTER.json`) with
new ids `GAP-056`..`GAP-078`. It records every defect found, and its current
status, in the remediation work that landed on top of the production merge
of PR #16 (`d72f57c6`, 2026-10-23) through 2026-11-03. No existing register
file was modified. Every fixing commit SHA below was verified to exist in
this worktree with `git cat-file -e <sha>` on 2026-11-03.

| ID | Severity | Subsystem | Status | Fixing SHA(s) |
|---|---:|---|---|---|
| GAP-056 | P0 | RQ3 evidence gate | fixed | `61769519` `a3773070` `020063d9` `1e902986` `119da123` `941eaa7c` (merged `b9b61518`/`a06c4b1e`) |
| GAP-057 | P0 | RQ5 train_launcher DDP init | fixed | `409c348d` `9d35e786` `74a16ab0` |
| GAP-058 | P0 | RQ5 fcn_resnet50 backbone weights | fixed | `a3b50e5c` |
| GAP-059 | P1 | rq5_contract_audit silent fallback | fixed | `6f4ced30` |
| GAP-060 | P1 | RQ5 disk guard keyword crash | fixed | `4c808f8d` |
| GAP-061 | P0 | P0-B orphan_road_repair (heading/contactPoint/reciprocal/junction/strict) | fixed | `f59212b3` `d3947e90` `ac3bb510` |
| GAP-062 | P1 | Missing road-link contactPoint defaulted silently | fixed | `f1c28580` |
| GAP-063 | P0 | Stage 7 unconditional LaneLinkBuilder wipe | fixed | `98e0d7e5` |
| GAP-064 | P0 | Non-atomic write_xodr (ENOSPC truncation) | fixed | `98e0d7e5` |
| GAP-065 | P1 | Access-metadata silent skip of unresolved roads | fixed | `98e0d7e5` |
| GAP-066 | P0 | capture_writer NameError on every semantic write | fixed | `4b3b0e9a` |
| GAP-067 | P1 | conftest.py / test_batch1 masking real carla client session-wide | fixed | `0b96a4f5` `72ce7790` |
| GAP-068 | P1 | Stage 8 lane-link advisory referenced undefined `fixed_out` | fixed | `cf5f8ffe` |
| GAP-069 | P0 | check_road_link_reciprocity junction-mediated exemption bypass/false-positive | fixed | `f1c28580` `8f22c704` `ed1bd069` `8c4424f0` |
| GAP-070 | P2 | 207 junction exits exceed combined carriageway width at reference line (real 07_lanes map) | **open** | -- |
| GAP-071 | P0 | export_thesis_tables.py exported superseded leaky RQ4 number | fixed | `2e0b764a` `1509c559` |
| GAP-072 | P0 | Deleted source inputs (dem_ing.tif, buildings.geojson) | fixed | `b09af15c` |
| GAP-073 | P1 | Unauthorized submission mirror edits outside allow-list | fixed | `fbe89271` |
| GAP-074 | P0 | RQ3 crop tool dropped all top-level `<controller>` elements while reporting PASS | fixed | `47284531` |
| GAP-075 | P2 | ValidationReport.add() reversed (stage, level, message) at ~9 call sites | **open** | -- |
| GAP-076 | P1 | OSM identity lost in OSM->XODR conversion | **open** | -- |
| GAP-077 | P0 | CARLA RPC handshake hang, 2026-11-03 | **blocked_external** | -- |
| GAP-078 | P2 | Shared venv stale editable finder + global PYTHONPATH | **open** | -- |

Counts: 23 tracked, 18 fixed, 4 open, 1 blocked_external.

## Evidence and residual risk detail

### GAP-056 -- RQ3 evidence gate false-pass
- **Evidence**: `61769519`, `a3773070`, `020063d9`, `1e902986` each close one
  named gate (G05/G01/G02/G03); `119da123` + `941eaa7c` add a signed, bound,
  independent review receipt (Ed25519) with fail-closed defaults; merges
  `b9b61518` and `a06c4b1e` land both lines on the integration branch.
  Regression: `ultimate_pipeline/tests/unit/test_rq3_review_receipt_binding.py`.
- **Residual risk**: no `review_trust_root` keyset exists in the repo, so a
  real independent review can never become authoritative by design --
  "no trust root means never authoritative" (119da123 commit message).
  Admission of a genuine independent review is `blocked_external` pending an
  operator-provisioned trust root.

### GAP-057 -- RQ5 train_launcher crash
`409c348d`/`9d35e786` fixed the original `is_main`-before-assignment crash;
`74a16ab0` found and removed a *duplicate* `_init_ddp` reintroduced by a later
merge, and retargeted the regression test at `_main_impl`. Fully fixed.

### GAP-061 -- P0-B orphan_road_repair
`ac3bb510`'s commit message documents the most serious defect precisely: a
hand-rolled chord projection along the END heading was "correct only for a
straight `<line>`"; `<arc>`/`<spiral>`/`<poly3>`/`<paramPoly3>` geometry fell
through to the same formula, producing up to a 16.7 m endpoint error. Fixed
by delegating to `ultimate_pipeline/geometry/opendrive_geometry_kernel.py`.

### GAP-069 / GAP-070 -- road-link reciprocity and the new map-geometry finding
`f1c28580` added the reciprocity check; `8f22c704` tightened the
junction-mediated exemption to require a backing `<connection>`; `ed1bd069`
found that requirement itself was wrong for one-way junction exits (a
`<connection>` never names the exit-side road, so 22,588 of 45,176 real
road-road links were false positives) and fixed exit-side backing;
`8c4424f0` found the exit-side check still didn't verify the connecting
road's own `@junction` attribute, closed that gap, and **separated** a
geometry check (reference-line gap vs. combined carriageway width) from the
structural check. On the real 07_lanes map (sha256 `787870ba...`,
read-only): **0 gated violations**. The geometry check surfaced a **new,
report-only finding**: 207 of 4,577 junction exits sit 3.5-7 m beyond the
combined carriageway width at the reference line -- likely the same
connector-geometry class already tracked as GAP-026 (MAP_DEFECT_CONFIRMED).
Per 8c4424f0's own commit message and per the GAP-026 rule (never fixed by
raising tolerance, no final-XODR cosmetic mutation), this is filed as
**GAP-070, open**, not silently resolved or gated.

### GAP-072 / GAP-073 -- unintended data loss and mirror drift
`f0c83285` deleted `cities/ingolstadt/dem/dem_ing.tif` (1,711,684 -> 0 bytes)
and all 177,221 lines of `cities/ingolstadt/osm/buildings.geojson` as
collateral of an unrelated CRS fix; restored by `b09af15c`. Separately,
`f34a12e6` edited 3 files under `submission/infrastructure/ultimate_pipeline/`
outside the 6-file `CRITICAL_MIRRORED_FILES` allow-list from the 2026-08-28
mirror-sync policy correction; reverted by `fbe89271`.

### GAP-075 -- ValidationReport.add() argument order
`ValidationReport.add(self, level, stage, message)`
(`ultimate_pipeline/core/validation_report.py:90`) is called with the
arguments reversed at 9 call sites, verified by grep on 2026-11-03:
`stage_04_enrichment.py:259,341,362,395`, `stage_08_integrity.py:814`,
`stage_09_positional_semantics.py:237,257,290,304`,
`stage_12_domain_gap.py:322`. Each passes a stage-name string as `level` and
the literal string `"error"` as `stage`, so intended error-level entries are
misfiled. `8c4424f0`'s own commit message explicitly deferred fixing this
("the same reversed order at 9 older call sites is left for a separate
change because fixing it moves entries from warnings to errors") -- i.e. a
real behavior-changing fix that needs its own assessment, not a drive-by
cosmetic patch. Still **open**.

### GAP-076 -- OSM identity in OSM->XODR conversion
`ultimate_pipeline/enrichment/osm_meta_index.py:16` documents in-repo that
XODR road ids are Osm2Odr/netconvert-assigned sequence numbers, not OSM way
ids. `netconvert --output.original-names` is available to carry OSM way ids
through conversion but is not wired into this pipeline's invocation
(`ultimate_pipeline/osm/osm_to_xodr.py`, `osm_to_xodr_wrapper.py`). Needs an
operator decision; not attempted here (source-stage-only fix, no final-XODR
cosmetic mutation permitted as a substitute). **Open**.

### GAP-077 -- CARLA RPC handshake hang
Reported runtime specifics (2 attempts, ~5.9/6.1 GB VRAM, no TDR, worked on
2026-10-21) were not independently reproduced in this worktree -- starting
CARLA is forbidden for this writer task. Independently confirmed from this
worktree on 2026-11-03: `df -h /c` shows the C: drive at 476G/476G used,
**92 MB free**, 100% use -- consistent with, though not proof of, a
resource-starvation contribution. **blocked_external**.

### GAP-078 -- shared venv / PYTHONPATH
Reported for a different worktree/environment (`F:\wt\authority-convergence-20261020`
editable finder + global `PYTHONPATH`). Not reproduced from this worktree:
here `PYTHONPATH` resolves to this project's own root, and no stale
authority-convergence finder was found. Recorded for tracking only. **Open.**
