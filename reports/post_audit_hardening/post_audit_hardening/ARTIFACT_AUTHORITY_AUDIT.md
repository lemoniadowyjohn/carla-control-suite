# ARTIFACT AUTHORITY AUDIT

- Date: 2026-09-24
- Mode: read-only (no production code changed)
- Question: how does the pipeline decide which generated artifact is authoritative, and can that authority be bypassed or corrupted?

## 1. Pipeline stage table

| # | Stage | Producer | Output path | Hash mechanism | Promotion | Consumer | Overwrite | Immutable |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S1 | Source inputs (OSM/buildings/DEM) | `scripts/regen_map_of_record.py::_verify_manifest` (107-142) via `ultimate_pipeline/governance/inputs_manifest.py:77` | `INPUTS_MANIFEST.json` paths | sha256 (`inputs_manifest.py:55`), fail-closed (77-171) | — | OSM→XODR seed | rewritable committed JSON | No |
| S2 | Intermediate XODR (Osm2Odr) | `regen_map_of_record.py:487-495` | `out_dir/seed_from_osm.xodr` | `_sha256_file` (`regen:67`) | — | pipeline input | `overwrite=True` (`regen:491`) | No (byte-nondeterminism noted 413-420) |
| S3 | Post-process/rebase/hygiene | `ultimate_pipeline.run_pipeline` (`regen:270`), stages 08/08h | `run_dir/08_final*.xodr`, `*_laneSectionFixed.xodr` | structural fp `artifact_authority.py:251-278`; `sha256_file:294` | — | next stage / receipt | same run dir | structure-frozen ledger only |
| S4 | Validation / acceptance | `measure_candidate_acceptance.run_gates` -> `build_map_acceptance` (`regen:336-356`) | `out_dir/map_acceptance.json` | sha bound to receipt (`artifact_authority.py:780-783`) | gate `valid_for_experiments` (`regen:527-529`) | candidate emit | overwrites | No |
| S5 | Final receipt | `artifact_authority.py::resolve_final_artifact_receipt` (338-430); `write_receipt` (825-835); written last in `main_pipeline:3262` | `final_artifact_receipt.json` | re-hash + bytes + fp vs receipt (384-394) | atomic `os.replace` (825-835) | rebase (`regen:294-306`) | overwritten on rerun | atomic write only; no registry link; not chmod RO |
| S6 | Candidate emit | `regen_map_of_record.py::_emit_candidate` (375-410) | `candidate/<ts>_map_of_record_*.xodr` | `emitted_candidate_sha256` (400-402) | `shutil.copy2` (378), **no guard** | registry pin | silent overwrite via `--candidate-name` (533-544) | No; provenance plain write (407) |
| S7 | Registry pin (map of record) | hand-edited `PINNED_MAP_REGISTRY` (`map_registry.py:702`); pre-pin gate `validate_candidate_registry_entry` (1498-1637) | path literal 739-742, sha at 741; supersedes chain 762-764 | `verify_pinned_map` re-hash (935, 1010-1016) | **manual code edit**; no code writes it | cook, import, certifiers | supersede chain only | registry = git code; on-disk XODR not RO |
| S8 | Tiling / FBX cook | `scripts/cook_full_grid_tiles.py:56-96`; `ultimate_pipeline/tiling/tile_fbx_generator.py` | `..._FULL_GRID_TILE_FBX_COOK/artifacts/tile_<x>_<y>/` | sha from `verify_pinned_map`, `_sha256` (cook:167) | re-resolve at exec (cook:284) + re-hash (313-317) | import package | CHKP overwritten per tile (109); COOK_RESULTS only at end (546) | tile reuse sha-gated (421-427) |
| S9 | Import package | `tools/stage_large_map_import_package.py:41-97,121-158` | `Import/<pkg>/...` | `verify_pinned_map` + `validate_staged_package(expected_xodr_sha256)` (143) | registry resolution (45) | CARLA import | overwrites pkg dir | No |
| S10 | Registry-bypassing consumers | `settings.py:181-244`; `artifact_locator.py:82-124`; `run_full_domain_gap.py:3397,7220,7236`; `run_thesis_experiments.py:29-32`; `tile_world_runner.py:157,184`; `output_discovery.py:5-36` | glob `08_final*.xodr` / `*.xodr` / tiles dir | sha rarely; never required | — | pipeline input, domain-gap, thesis, live tile loads | newest-by-mtime wins | No |

## 2. Answers

**Q1. Can a stale artifact accidentally be consumed? — YES.**
`settings.py:225` globs `08_final*.xodr` across run dirs, sorts by `st_mtime` (241), and becomes the next run's input (`settings.py:1837-1840`). Same pattern in `artifact_locator.py:112-124`, `run_full_domain_gap.py:7220/7236`, `run_thesis_experiments.py:29-32`. A touched/restored older final wins; no receipt/sha gate.

**Q2. Can two different files claim to be map-of-record? — YES (confirmed live).**
- Registry pin `auto_map_of_record` -> `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr`, sha `370abbbb…` (`map_registry.py:739-742`).
- Campaign manifests promote `perception_candidate` -> `ingolstadt_perception_final.xodr`, sha `248ffbbe…`, role "governed perception load payload" (`campaigns/ingolstadt_cooked_perception_v1/manifest.json:557-567` and `candidate/manifest.json:452-462`), but with `readiness_state: REVIEW_RESTORED_PENDING_CLAUDE_C0`, `c0_accepted:false`, `perception_candidate_accepted:false`, `release_authority:false` (`manifest.json:13-25`).
- `stage_c2_govern_promote.py` writes the campaign manifest (`perception_candidate`, 117-128), `PROMOTION_RECORD.json` (176), and governed payload atomically, but never writes `PINNED_MAP_REGISTRY` (only readers: `tools/validate_thesis_claim_provenance.py:138,161`, `tools/pack_thesis_run.py:85`). Two promotion authorities exist and are disjoint.

**Q3. Does every consumer resolve through registry authority? — NO.**
Yes: cook (`cook_full_grid_tiles.py:56,65,284`), import stage (41-45), certifiers (`certify_ingolstadt.py:350,479`), `task_c1*` (10-16), `topology_oracle.py:13`, `regen_local_registration.py:36`, `regen_frechet_distance.py:35`. No: pipeline input (`settings.py:1837-1840`), domain-gap (`run_full_domain_gap.py:7220`), thesis (`run_thesis_experiments.py:29-32`), live tile loads (`tile_world_runner.py:157,184`).

**Q4. Can basename/path selection bypass the registry? — YES.**
`settings.py:225` `glob("08_final*.xodr")`; `run_full_domain_gap.py:3397` lexicographic `sorted(glob(...))`; `check_osm_to_carla_determinism.py:34` filename sort; `tile_world_runner.py:157/184` sorted glob; `output_discovery.py:34` dir mtime. Cook derives `HEADER_OFFSET_XY` from the registry now (cook:96); older consumers don't.

**Q5. Is final SHA verified before downstream use? — PARTIALLY.**
Cook: yes — import-time `verify_pinned_map` (65), execution-time re-resolution (284), re-hash vs receipt (313-317), tile-reuse sha gate (421-427). Import: yes (143). Pipeline input: **no** — only `isfile` (`main_pipeline.py:1803`); `_resolve_input_xodr_with_fallback` never hashes (settings.py:181-244).

**Q6. Are promotion receipts immutable? — NO.**
`write_receipt` is atomic at write (825-835) but the file is writable/overwritable on rerun; no chmod RO, no chained receipt, no `registry_sha256` link ("cook:343 reads the pin receipt, not `final_artifact_receipt.json`"). `regen_provenance.json` (regen:407) and `PROMOTION_RECORD.json` (stage_c2:176) are plain writes. Only the registry supersedes graph + git provide durability.

**Q7. Can a failed pipeline leave a seemingly valid final artifact? — YES.**
Final 08_final/08h XODRs are written before the terminal receipt; a crash between stage 08 and `main_pipeline.py:3262` leaves a complete-looking XODR with no receipt. `resolve_final_artifact_receipt` fails closed (348-351) but mtime consumers consume the orphan as authoritative. `_emit_candidate`'s `shutil.copy2` (378) is non-atomic with no existing-file guard. Cook's `CHECKPOINT.json` is overwritten per tile (109) while `COOK_RESULTS.json` lands only at the end (546).

## 3. Demonstrated defects + proposed bounded fixes

1. **Dual governed authority (Q2).** Pin `370abbbb…` vs unaccepted `perception_candidate` `248ffbbe…`. Fix: retire `perception_candidate` from both manifests (its own flags reject it); add `registry_sha256` cross-ref; stop `stage_c2_govern_promote.py` writing that pointer (117-128).
2. **mtime-authoritative pipeline input (Q1/Q4).** `settings.py:181-244`. Fix: require a `final_artifact_receipt.json` + sha match in the run dir before selection; remove the mtime tie-break.
3. **Unverified pipeline input (Q5).** `main_pipeline.py:1803` `isfile` only. Fix: verify `UP_INPUT_XODR` sha against INPUTS_MANIFEST at start, fail closed.
4. **Non-atomic overwriting emit (Q7).** `shutil.copy2` (regen:378) + `--candidate-name` overwrite. Fix: reuse `atomic_write_payload_bytes` (`phase_q/governed_payload.py:227-282`); refuse names matching any registry pin path; write provenance atomically.
5. **Basename/lexicographic selection (Q4).** `run_full_domain_gap.py:3397`; `tile_world_runner.py:157/184`; `output_discovery.py:34`. Fix: gate each on a registry-resolved tiles dir/sha.
6. **Receipts not registry-linked nor RO (Q6).** Fix: add `registry_sha256` to final receipts; chmod 0444 post-`os.replace`; verify on read.
7. **Cook partial-progress artifact (Q7).** Fix: write final COOK_RESULTS atomically with tiles-completed/total + pin sha.
8. **Manifest duplication (Q2).** Two copies of `perception_candidate` (root and candidate manifests). Fix: single source of truth.
9. **Orphan candidates.** 28 `*map_of_record*.xodr` files on disk, some unregistered. Fix: extend `audit_registry` (`map_registry.py:1701`) to classify registered/superseded/orphan and fail on actionable orphans.

No production code was changed on this pass.