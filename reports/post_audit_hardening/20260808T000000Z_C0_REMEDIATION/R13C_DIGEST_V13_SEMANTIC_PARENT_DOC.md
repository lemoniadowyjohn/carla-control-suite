# R13C — Semantic-parent authority v2 + digest v13 discriminator (evidence digest)

*Status: COMPLETE — evidence produced by `stage_r13_production.py` (R13 batch,
run `20260808T000000Z_C0_REMEDIATION`).*

## 1. Purpose

The semantic parent (`candidate_g_semantic_enriched.xodr`) is the accepted
3467-signal parent of the whole C0 remediation. `R13E` proves — against the
**real parent bytes** — that the protected-digest vocabulary now covers all 13
categories the C0 semantic-write contract freezes, while every v1 category
digest stays byte-identical to the frozen v1 authority (`R04`).

## 2. Frozen parent identity (from `R13E`)

| Field | Value |
| --- | --- |
| name | `candidate_g_semantic_enriched` |
| path | `reports/post_audit_hardening/20260807T000000Z/candidate_g_semantic_enriched.xodr` |
| `sha256_lf_text` | `d604ac393e12730ed276f5c865d0ef82c8a537b97bd8d79beeddd4c96863e470` |
| counts | roads 32710, junctions 3646, laneSections 32710, signals 3467, signalReferences 0, controllers 0, objects 0 |
| provisional | false (NOT PROVISIONAL_PRE_C0) |

## 3. The 13 protected digest categories

Structural (9, `phase_q/structural_digest.py::structural_digests_v2`):

PLANVIEW, ROAD_LINK, JUNCTION_CONNECTION, LANELINK, LANESECTION, ELEVATION,
SUPERELEVATION_CROSSFALL, ROADMARK, CONNECTOR_REPAIR

Traffic control (4, `phase_q/signal_digest.py::traffic_control_digests_v2`):

SIGNAL_ELEMENT, SIGNAL_REFERENCE, CONTROLLER, COMBINED_TRAFFIC_CONTROL

Collection states (`PRESENT` / `EMPTY_COLLECTION` / `MISSING_COLLECTION` /
`PARSE_FAILURE`) are part of the digest input, so the same document can never
collapse an empty collection onto a missing one (count-only collapse defect).

## 4. Real-parent results (from `R13E`)

| Category | State on parent |
| --- | --- |
| SUPER_CROSSFALL | `MISSING_COLLECTION` (map genuinely carries no super/cross- profiles — read-only) |
| ROADMARK | `PRESENT` |
| CONNECTOR_REPAIR | `PRESENT` (all 12 repaired connector road ids: 50003, 51425, 51646, 52738, 54261, 56874, 57300, 58404, 62170, 66369, 68135, 69106) |
| traffic control combined | `b48272854cc2c995ebf327d397111d712f118c558f5973940ea139620c034dfbbb` |

All `R13E` gates pass (`SEMANTIC_PARENT_AUTHORITY_V2`): counts, 12 connector
repairs present, v2 traffic-control digest identical to `R04`, and the six v1
structural categories byte-identical to `R04` (`v1_byte_compatibility` all
true). The v13 *combined* structural digest differs from v1 *combined* by
design: it now also spans SUPERELEVATION_CROSSFALL/ROADMARK/CONNECTOR_REPAIR.

## 5. Discriminator evidence (executable, R13D)

Seven cases executed against `phase_q/signal_digest.py::traffic_control_digests_v2[_from_text]` — all pass:

1. `EMPTY != MISSING` (distinct collection states)
2. `EMPTY != PARSE_FAILURE` (sentinel, not a sha of empty)
3. `EMPTY != count-only sha256("0")`
4. adding one `signalReference` changes the ref digest
5. semantic mutation changes the digest at the same count
6. reordering records does NOT change the digest
7. all four collection states are distinct

Regression tests: `tests/test_r13_digest_v2.py`, `tests/test_r13_mutation_allowlist.py`, `tests/test_r13_governed_payload_guard.py`, `tests/test_r13_evidence.py`. Full suite `2669 passed, 78 skipped`.

## 6. Gate

The single enrichment gate (`phase_q/mutation_allowlist.py::parent_hard_gate`,
fail-closed, allowlist = exactly `object:INSERT_OBJECT_CROSSWALK`) passes the
real parent and hard-rejects the negative control `ingolstadt_fixed_final.xodr`
(SIGNAL_COUNT_MISMATCH expected=3467 got=0, PARENT_SHA256_MISMATCH,
COMBINED_TC_DIGEST_MISMATCH) — `R13N`.