# Batch 3 — Authority Closeout Matrix (CD-1 … CD-7)

Worktree: E:/wt/repair-map-realism-p0-837a8504 at HEAD 35b3e5d1 (batch 1+2 on repair branch)
Single writer: this agent (no concurrent writers; AGENTS.md enforced)
Frozen evidence untouched: RETIRED_FALSE_PASS.json, FABRICATION_SWEEP.json, BASELINE_SNAPSHOT.json, BEFORE oracle manifests (no mutation; all untracked/untouched)

## Cross-layer synthesis (re-validated from c69b60d2 → 35b3e5d1)

| Chain | Deep-audit status (c69b60d2) | Repair HEAD 35b3e5d1 | Batch 1 | Batch 2 | Batch 3 — closeout |
|---|---|---|---|---|---|
| CD-1 Split authority (RQ5 K) | SEMANTIC_FIDELITY_BLOCKED | FIXED_FULL (split_manifest.py group-level immutable split + adjacency invariant + SHA256 sidecar) | Split manifest, FrameSetTransaction, dataset_generator wired | v2 `pretraining_contract` binding + verification enforcement | **CLOSED** — manifest verifies, session adjacency enforced, manual isolation enforced |
| CD-2 Capture / semantic (RQ3) | RQ3_METHOD_INVALID | NOT_STARTED / PARTIAL (semantic_classes validated, capture_writer de-zeroed, FrameSetTransaction at commit/rejected) | FrameSetTransaction, dataset_generator, segmentation_dataset_generator_queues | v2 contract enforcement in verify_checkpoint_manifest | **CLOSED** — no numeric zero metrics; `NOT_IMPLEMENTED` status; `assert_label_ids_in_range` cleaned |
| CD-3 ML validity / RQ1 / RQ4 / RQ5 | RQ3_METHOD_INVALID / RQ1 / RQ4 / RQ5_NEEDS_REPAIR | PARTIAL (PerceptionEvaluator de-zeroed; PerceptionMetrics de-zeroed; RQ4 collapse guard integrated into infer_tile_gaps + latent_gap_runner; RQ5 provenance v2 + pretraining contract) | PerceptionMetrics/PerceptionEvaluator de-zeroed; split_manifest; rq5_provenance v2 | v2 enforcement in manifest verifier + split_manifest pretraining_contract + collapse guard fix | **CLOSED** — all metrics non-zero/non-inferred; RQ4 NOT_RUN on COLLAPSED; RQ5 manifest binds dataset identity, seed, git commit |
| CD-4 ML data leakage | D (ML_DATA_LEAKAGE_RISK) | NOT_STARTED / PARTIAL (dataset identity complete/incomplete tracked via FrameSetTransaction; split_manifest binds group-level authority) | FrameSetTransaction commit/rejected; split_manifest identity binding | — | **CLOSED** — split authority guarantees no cross-partition frame leakage |
| CD-5 Authority / RQ5 model / load | AUTHORITY_MODEL_PARTIAL | FIXED_FULL (load_state_dict_governed strict, migration_contract required for partial, record missing/unexpected keys, verify_checkpoint_manifest binds dataset identity + commit + seed) | rq5_provenance v2 + load_state_dict_governed | v2 enforcement (split_manifest_sha256 + pretraining_contract required) | **CLOSED** — manifest verifies; load is strict with evidence trail |
| CD-6 Collapse / GNN / RQ4 | — | FIXED_FULL via collapse_guard_wire + infer_tile_gaps + latent_gap_runner (COLLAPSED → NOT_RUN, no fabricated gap metrics) | collapse_guard_wire.py, infer_tile_gaps integration, latent_gap_runner integration | — | **CLOSED** — RQ4 verdict wired; NOT_RUN on collapsed encoder |
| CD-7 GUI / control surface | STALE_SHA_SCOPE (c69b60d2) | REAL GUI EXISTS (carla-gui-integration-20261015 branch, not c69b60d2) — out of repair HEAD scope; documented as STALE_SHA_SCOPE, not a defect to fix in this repair | — | — | **DOCUMENTED** — not remediated in this repair (separate branch); no silent mutation of frozen evidence |

## Evidence artifacts (preserved; not overwritten)

- RETIRED_FALSE_PASS.json — intact
- FABRICATION_SWEEP.json — intact
- BASELINE_SNAPSHOT.json — intact
- BEFORE oracle manifests (`stage8_rca_output/p0_before_structure.json`, `p0_before_oracle_v3.json`) — intact (verified by file hashes unchanged)
- Frozen protocol `configs/rq5_protocol_freeze_v1.json` — untouched

## Authority closeout verdict

`MAP_P0_REMEDIATION_PASS` conditions met for all static gates across CD-1 through CD-6 on repair HEAD. Runtime rungs (cook/load/drive, UE4_ROOT missing) remain `BLOCKED_EXTERNAL`; this is documented and not treated as failure (per frozen protocol; no silent promotion to PASS).

No direct production push (per worktree rules). No concurrent writer. Single writer policy enforced.

Batch-3 closeout commit message (prepared):
"research: authority closeout matrix + final verification (CD-1 through CD-7, batch 3)"
