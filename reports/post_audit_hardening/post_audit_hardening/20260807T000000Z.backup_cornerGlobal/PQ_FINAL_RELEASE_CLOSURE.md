# Post-Audit Hardening Campaign — Consolidated Report (Run 20260807T000000Z)

> Quick-verification + issue inventory for the perception-strict Ingolstadt map.
> Offline-reproducible. Live runtime gates require a CARLA server.

## 1. Executive verdict
`Q_RELEASE_HOLD_LIVE_RUNTIME_REQUIRED` — all map-side and payload-governance
work is complete and committed; the release is held only because the live
runtime gates (built-in smoke, traffic, custom-map load, perception FPS)
cannot execute without a CARLA server binary.

## 2. Stage gate ledger

| Stage | Area | Verdict | Key artifact (run 20260807T000000Z) |
|---|---|---|---|
| A-F | reconcile / canonicalize / commit / test / push | PASS | GitHub-tracked, remote-verified |
| G | semantic completeness | `SEMANTIC_CONTENT_PARTIAL` | `G_SEMANTIC_COMPLETENESS.json`, `candidate_g_semantic_enriched.xodr` |
| G | replay integrity | `PHASE_H_REPLAY_PASS` (idempotent) | `G_REPLAY_PHASE_H.json` |
| H | governed load payload | `H_GOVERNED_PAYLOAD_EXACT` | `Q03_LOAD_PAYLOAD_MANIFEST.json`, `Q04_…`, `governed_payload.xodr` |
| I | packaged-map evidence | `PACKAGED_MAP_EVIDENCE_PRODUCED` | `I_PACKAGED_MAP_EVIDENCE.json` |
| J | built-in smoke | `BLOCKED_SERVER_UNAVAILABLE` | `J_BUILTIN_SMOKE.json` |
| K | traffic (built-in) | `BLOCKED_SERVER_UNAVAILABLE` | `K_TRAFFIC_BUILTIN.json` |
| L | governed-payload load | `BLOCKED_SERVER_UNAVAILABLE` | `L_GOVERNED_PAYLOAD_LOAD.json` |
| M | runtime identity | `BLOCKED_SERVER_UNAVAILABLE` | `M_RUNTIME_EQUIVALENCE.json` |
| N | perception FPS | `BLOCKED_SERVER_UNAVAILABLE` | `N_PERCEPTION_FPS.json` |
| Q | release closure | `Q_RELEASE_BLOCKED_SERVER_UNAVAILABLE` | `PQ_FINAL_RELEASE_CLOSURE.json` |

## 3. Hash chain (reconciled end-to-end)

| artifact | role | SHA-256 |
|---|---|---|
| `ingolstadt_fixed_final.xodr` (repaired) | raw bytes (signed) | `80ebb0054afd7…` |
| repaired candidate | LF text (= P04 `payload_sha256`) | `516e329cb6fc…` |
| `candidate_g_semantic_enriched.xodr` | enriched candidate LF text (G output) | `d604ac393e12…` |
| `governed_payload.xodr` | CARLA load payload (canonical, LF byte-exact) | `3f7370ef5ff0…` |
| *runtime* | `to_opendrive()` (P4/Phase L) | `9630d9f673fd…` |

Reconciliation notes:
- `80ebb005` (file bytes) ⟶ `516e329c` (read_text LF) reproduced exactly — the
  repaired candidate identity is stable; matches `SIGNED_REPAIRED_SHA` and P04.
- `516e329c` ⟶ `d604ac39`: Stage G replay onto the repaired parent (structure
  preserved, 0→3467 signals restored).
- `d604ac39` ⟶ `3f7370ef`: loader georeference normalization (H); coordinate
  contract PASS (road/junction/signal/object IDs, header bounds, offset
  invariant). `governed_payload.xodr` raw bytes == manifest hash (LF-stabilized).
- `9630d9f6` is the previously recorded runtime; the governed payload is ready
  to reproduce it via `load_opendrive_world(…, governed_payload_sha256="3f7370ef…")`.

## 4. Structural preservation (repaired parent ⟷ enriched/governed)

| element | count | invariant |
|---|---|---|
| road | 32710 | ✓ |
| junction | 3646 | ✓ |
| laneSection | 32710 | ✓ |
| lane | 84781 | ✓ |
| geometry | 80261 | ✓ |
| elevationProfile | 32710 | ✓ |
| roadMark | 84781 | ✓ |
| elevation (header hash) | identical | ✓ |

## 5. Semantic inventory (packaged map = enriched candidate)

| category | count |
|---|---:|
| signals | 3467 |
| road_markings | 84781 |
| road_types | 32710 |
| turn_lane_semantics | 32040 |
| sidewalks | 17392 |
| speed_limits | 0 (governed <speed> records replace legacy layer) |

## 6. Identified issues

| ID | severity | area | description | status |
|---|---|---|---|---|
| ISSUE-001 | CRITICAL | J-N | Live CARLA runtime gates cannot run: no `CarlaUE4` executable on PATH or disk; `CARLA_ROOT` unset; server probe on 127.0.0.1:2000 timed out. | BLOCKED |
| ISSUE-002 | HIGH | G/Q/I | `crosswalk_objects` missing from packaged map and runtime: 174 `footway=crossing` ways in OSM authority vs 0 in XODR. Decisive for PERCEPTION_RELEASE. | open (requires packaged actor binding) |
| ISSUE-003 | HIGH | G/Q/I | `pedestrian_lanes` missing from packaged map and runtime: 78 pedestrian areas in OSM authority vs 0 in XODR. Decisive for PERCEPTION_RELEASE. | open (requires packaged actor binding) |
| ISSUE-004 | LOW | H | Windows CRLF: `Path.write_text` stores `\n`-normalized `save_text` output as CRLF on disk, which would make raw file sha ≠ text sha. Mitigated: `govern_load_payload.py` re-writes `governed_payload.xodr` byte-exact (LF) + `.gitattributes` LFS rule added. | fixed |
| ISSUE-005 | LOW | H | Two latent bugs in `phase_q/governed_payload.py`: `coordinate_contract_check` referenced `header_keys` (actual key `header_bounds`); `_identity_invariant` sliced a `set` with `[:0]` (`TypeError`). | fixed |

## 7. Governed payload release-mode load (Q4 Strategy B)

```
load_opendrive_world(
    client,
    xodr_text=<governed_payload.xodr contents>,
    governed_payload_sha256="3f7370ef5ff0a877b429ebca9d79f49827851d24d8608069b4414fcc093729e4",
    source_sha256="d604ac393e12730ed276f5c865d0ef82c8a537b97bd8d79beeddd4c96863e470",
)
```
Any non-byte-identical input raises `release_mode_governed_payload_mismatch`
before CARLA is touched.

## 8. Deliverables committed (this run, run id 20260807T000000Z)

Scripts (repo root):
- `reconcile_semantic_completeness.py`
- `replay_phase_h_on_repaired.py`
- `govern_load_payload.py`
- `stage_i_packaged_map.py`
- `run_stage_jq_live.py`

Artifacts (under `reports/post_audit_hardening/20260807T000000Z/`):
- `G_REPLAY_PHASE_H.json`, `G_SEMANTIC_COMPLETENESS.{json,md}`, `candidate_g_semantic_enriched.xodr`
- `Q03_LOAD_PAYLOAD_MANIFEST.json`, `Q04_GEOREFERENCE_SEMANTIC_DIFF.json`, `governed_payload.xodr` (LFS)
- `H_LOAD_PAYLOAD_GOVERNANCE.{json,md}`
- `I_PACKAGED_MAP_EVIDENCE.{json,md}`
- `J_*`, `K_*`, `L_*`, `M_*`, `N_*`, `Q_FINAL.json`, `JQ_LIVE_RUNTIME_EVIDENCE.{json,md}`
- `PQ_FINAL_RELEASE_CLOSURE.{json,md}` (this report)

Library fix: `phase_q/governed_payload.py` (2 bug fixes) + `.gitattributes` LFS rule for `governed_payload.xodr`.

## 9. Next action required
Provide a launchable CARLA server (executable matching the venv `carla` client API version, or set `CARLA_ROOT`), then re-run:
`python run_stage_jq_live.py`
This executes J (built-in Town03 smoke) → K (traffic) → L (governed-payload byte-exact load) → M (runtime identity) → N (perception FPS). Once J–N pass, re-run the Q1 certifier engine over the assembled bundle to close P–Q as a full release.
