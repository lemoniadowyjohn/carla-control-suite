# Post-PR16 remediation: RQ3 gate hardening, RQ5 launcher fixes, topology safety, RQ4 evidence, RQ3 crop tool

**Base:** `integration/production-large-map-20260918` (`d72f57c6`)
**Head:** `integration/post-pr16-final-20261102` (`00098cf6`)
**CI:** "offline research gates" on `a6d10396` (last code change) — **success** (run 41869618929). `682e710a` (run 41704108450), `c5d0505f` and `bdc91ca3` also passed. The 3 commits after `a6d10396` are docs/reports only.

## Why

PR #16 was merged from `5a004113`. The G01/G02/G03/G05 gate fixes had never been pushed, so production still has these defects:
- the RQ3 evidence gate admits fake evidence (`terminal_status=FAILED`, made-up digests and a bare `"APPROVED"` → `EXPERIMENTAL_EVIDENCE_AUTHORITATIVE`);
- every RQ5 training launch crashes (`is_main` is read before it is assigned);
- DEM and building inputs are deleted;
- several other defects, listed below.

## What changes

**RQ3 evidence gate (G01–G05, C1)**
- Admission requires a `COMPLETED` terminal, an empty reason list and digests that resolve to real file bytes.
- The independent review receipt is a dedicated artifact. It must be Ed25519-signed by a key in `review_trust_root`, bound to the exact dataset and capture digests and to the session, with expiry and revocation checks. The reviewer must not be the capture operator; the comparison ignores case and surrounding whitespace. Receipts are capped at 64 KiB.
- The three admission digests must be distinct, and none may reuse a capture-frame digest.
- Missing `modality`, `committed` or `session_id` fields now fail closed instead of defaulting to a pass.
- There is no trust root yet, so no dataset can be admitted. That is by design.

**Frame-count contract (G03).** Expected counts are mandatory and must match exactly. Non-integer, bool and zero expectations are rejected.

**RQ5 training (CHAT-09)**
- `is_main` is now assigned before use, with a single DDP initialisation, rank-safe stale-SUCCESS revocation and DDP cleanup on every exit path.
- All four model builders pass `weights_backbone=None`; torchvision 0.24 otherwise loads ImageNet weights, which contradicts both frozen protocols. The pretraining receipt now records the arguments actually passed instead of a hard-coded value.
- `--contract` no longer silently falls back to the default contract when the given path is missing.
- The disk guard was called with a keyword it doesn't accept, which would have crashed real training; fixed.

**Topology and successor/predecessor links**
- **P0-B orphan repair:**
  - endpoints come from the canonical geometry kernel (paramPoly3 was off by up to 16.7 m);
  - predecessor/successor is chosen from the matching end, `contactPoint` is always set, and a reciprocal link is written;
  - roads inside junctions and already-occupied link slots are refused;
  - heading and height limits apply, with a 5 m default snap;
  - failures propagate under `THESIS_STRICT`.
- Removed Stage 7's unannounced wipe-and-rebuild of every junction laneLink (added by `0c08412f`). It undid the reviewed GAP-026 remap and changed 822 links on a real run.
- A missing `contactPoint` on a road-type link is now reported instead of assumed to be `"start"`.
- New check: road links must have matching reciprocal links. A junction exit is backed when the connecting road is listed in that junction AND its `junction` attribute names it. This is gated under `THESIS_STRICT`; the real map has **0 violations** across 45,176 links.
- Exit geometry is reported but not gated: the reference-line gap must not exceed the combined carriageway width. 4,370 of 4,577 real exits pass and 500 of 500 random unrelated roads are rejected. **207 exits fall 3.5–7 m short, a pre-existing map defect (GAP-070, open, GAP-026 class).**
- Stage 8's lane-link advisory had referenced an undefined `fixed_out` since `714ed04c` and never ran; fixed.

**I/O and enrichment**
- Atomic `write_xodr` (temp file + fsync + `os.replace`), byte-identical to the previous output (RQ1 determinism preserved). Stage 6 reports are written atomically too.
- Access-metadata enrichment fails closed on unresolved road IDs.

**Inputs and repository hygiene**
- Restored `cities/ingolstadt/dem/dem_ing.tif` and `osm/buildings.geojson` (deleted by `f0c83285`).
- Reverted 3 `submission/infrastructure` files that are not on the critical mirror list.
- Removed hard-coded `E:/wt/...` paths.

**Perception**
- `capture_writer.py` crashed with a `NameError` on every label write; fixed.
- The augmentor's `apply()` uses the instance's config.
- Two test files replaced the real `carla` module for the whole test session; fixed.
- A stale test is aligned with the CD-2 "not implemented" contract.

**RQ4 evidence**
- `tools/export_thesis_tables.py` now uses the GAP-010 leak-free retrain: cosine distance **0.921**, 95% CI [0.845, 0.976]. The superseded 0.643 is kept as `superseded_value`.
- New table: `reports/production_readiness/20261102T000000Z_RQ_TABLES_REFRESH/`. C19 is untouched.
- The README's RQ4 status is corrected.

**RQ3 auto-map crop tool (new)**
- `tools/rq3_crop_auto_to_manual_footprint.py` + `ultimate_pipeline/domain_gap/footprint_crop.py`.
- Derives a pure-subset, deterministic and registry-verified crop of the map-of-record to Grid0828's footprint.
- Real map: 3,584 roads and 450 junctions, 0 dangling references, sha256 `b2bc2712…`; covers 100% of Grid0828; 393 of 400 sampled roads are byte-identical to the source (the rest differ only by removed links).
- Review fix: `<controller>` elements were silently dropped while the run still reported PASS. Controllers are now preserved and pruned, every top-level element kind is accounted for, and two new hard checks guard this (`controller_references_resolve`, `no_unaccounted_top_level_loss`).
- Loading it in CARLA is **not yet verified**: the pilot is blocked on the runtime (see below).

**Late additions (`6885dfc2`..`c5d0505f`)**
- On a machine without the CARLA client, the real-client tests now skip instead of failing on the offline stub. All three call sites were fixed, and the skip was verified with a simulated carla-less run.
- 26 `ValidationReport.add()` calls in stages 4, 5, 7, 8, 9 and 12 passed (stage, level) and are now level-first. Errors, skips and successes were all being filed as warnings. This is report-only: no gate reads these buckets. 619 stage tests pass.
- Dead duplicate check removed from the crop tool's out-dir guard.
- `capture_writer.py` comment corrected. **Note: the subject of `8bb513fd` says "single atomic write", but the change was deliberately declined** (its body explains why: the outer wrap guards against a non-atomic writer, and a test depends on it). Only the comment changed.
- GAP-070 characterised in `GAP-070_CHARACTERIZATION.md`: 207 real defects, of two kinds. 147 are ~53° tangent kinks and 60 are up to 7 m positional offsets. They are the GAP-026 class, but at the connector's exit interface.

- New report-only check `junction_exit_heading_discontinuity` (`bbabe38c`). On the real map, 3,720 junction exits turn more than 30 degrees at the connector boundary, 3,391 of them at about 53 degrees. The geometry kernel's headings were cross-checked against finite differences (79 of 80 agree). The 111 exits at 170-180 degrees are mostly 0.1 m connector stubs with reversed heading; it is not a checker error. See `GAP-070_HEADING_MEASUREMENT.md`.

**GAP-070 root cause and report hygiene (`743edd65`..`00098cf6`)**
- **GAP-070 root cause found** (`46708baa`): the default-on junction connector snap (`tools/junction_connector_snap.py`, run in stage 5) moves each connector's start, including its heading, without re-fitting its curve. That rotates the connector, so it no longer meets the exit road. Reproduced in memory: heading kinks 351 → 3,720. **The fix is not in this PR.** It is on `fix/gap070-connector-snap-exit-20261103` and waits for a governed regeneration (X8).
- **All `ValidationReport.add()` calls now pass the level first.** `7df27c80` fixes the 20 remaining calls: 11 in `main_pipeline.py`, including 3 errors that were being filed as warnings, and 9 in `quality/`. A guard test (`e44e6aae`, widened in `7df27c80`) now scans the whole package: 59 calls, 0 violations. This only changes report contents: gate decisions still come from `get_failures()`, which is unchanged.
- A test no longer writes `run_identity.json` into the repository root (`5a055542`).
- **Gap register addendum 2** (`70b64831`):
  - GAP-075 is fixed and GAP-067's leftover issue is closed;
  - the GAP-070 root cause is recorded, with status still open;
  - new GAP-079: 0.1 m reversed connector stubs. All of them carry lane routing, so they must not be deleted by length.
  - The combined register has 24 entries: 19 fixed, 4 open, 1 blocked.
- RQ3 crop tool usage doc: `docs/research/RQ3_AUTO_MAP_CROP_TOOL.md` (`c758c830`, `00098cf6`).

**Gap register.** New addendum `reports/production_readiness/20261103T000000Z_GAP_REGISTER_ADDENDUM/`: GAP-056..GAP-078, 18 fixed, 4 open, 1 blocked. Each fix cites its commit. The historical registers are untouched.

## Verification

- Reviews: independent adversarial reviews, each with attack inputs beyond the tests; all APPROVE after fix rounds. The final review round found two more defects: the crop tool dropped controllers, and the junction-exit exemption ignored road B. Both are fixed in `47284531` and `8c4424f0`.
- Chunked full suite at the final code (`30a754cb`): **8362 passed, 3 failed**. 2 are the venv environment issue. The third is the training dry-run, aborted by its disk guard (272 MB free on E:, 512 MB required); it passes on its own. The earlier run at `ebe80121`: 8350 passed, 3 failed. 2 are the venv environment issue. The third is a training test whose disk guard correctly refused to write when E: had less than 512 MB free; it passes on its own.
- Full suite at `ed1bd069`: 8313 passed, 17 failed.
  - 15 failures were one test file leaking a `carla` stub; fixed in `72ce7790` and verified by an ordered re-run.
  - 2 are environment-only: a stale editable install in the shared venv.
- Protocol freezes unchanged: rq3 `5aa8ae24…`, rq5 `db7155fe…`. No historical `reports/` file modified.

## Not in this PR / known open

- **RQ3/RQ5 are still not measured.** The CARLA pilot on the crop failed twice at the RPC handshake (VRAM full, no driver reset); a retry needs free space on C:.
- **Admission is impossible by design:** it needs an operator-supplied review trust root and a signed external review.
- **Paired routes** need surveyed same-place anchors.
- **Lane links vs OSM:** junction laneLinks still use inner-first pairing, not OSM `turn:lanes`. Exact OSM IDs (netconvert `--output.original-names`) need a converter decision.
- **Junction exit geometry (GAP-070):** root cause found and a fix measured (exit kinks 3,720 → 349 on the stage-5 input), but the fix is on a separate branch until a governed regeneration (X8, needs ≥ 15 GB free disk) confirms it.
- **GAP-079:** ~0.1 m reversed connector stubs (58 from Osm2Odr and 23 more from the netconvert repair) are inventoried, not fixed. Which netconvert option creates them is still being investigated (X9b).
