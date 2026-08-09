# R14 CLAUDE C1 PACKET

*Run: `20260809T000000Z_C1_GENERATION` · branch `fix/post-audit-phase-e-junctions-roundabouts-20260803` · C1 candidate frozen before Claude C1 review (§Freeze)*

## Purpose

C1 candidate generation authorized by Claude's terminal C0-R acceptance
(`CLAUDE_SEMANTIC_WRITE_CONTRACT_ACCEPTED`). This batch regenerates the
crosswalk-enriched candidate from the accepted semantic parent under the
accepted mutation contract, proves lineage/determinism/idempotency, and
freezes the result for C1 review. It is OFFLINE-ONLY: no CARLA runtime,
no governance tagging, no promotion. Promotion remains gated on
`CLAUDE_SEMANTIC_CANDIDATE_ACCEPTED`.

## Claimed anchors

| Anchor | Value |
| --- | --- |
| Semantic parent | `reports/post_audit_hardening/20260807T000000Z/candidate_g_semantic_enriched.xodr` |
| Parent sha256_lf_text | `d604ac393e12730ed276f5c865d0ef82c8a537b97bd8d79beeddd4c96863e470` |
| signals / junctions / roads | 3467 / 3646 / 32710 · provisional=false |
| Mutation | `object:INSERT_OBJECT_CROSSWALK` (allowlist, cornerLocal only, `id=crosswalk_{osm_id}`, names controlled) |
| Frozen authority | S03/S04/S05 in the 20260807 run dir |

## C1.1 — candidate regeneration (lineage)

Producer: `stage_c1_generation.py` + accepted `CrosswalkInjector` from
`ultimate_pipeline/enrichment/object_injector.py` + `parent_hard_gate`
(mutation_allowlist). Families from the S07 crossing authority
(`INSERTED` 61 + `DUPLICATE_MERGED` 5 = 66 authored crosswalks).

- candidate: `candidate_crosswalk_enriched.xodr`
  (inside `reports/post_audit_hardening/20260809T000000Z_C1_GENERATION/`)
- candidate `sha256_lf_text` = `16ea2ec134b10d07518c63e1bd42c4ffd8b96113d1a52c0fe448f201c004d11f`
- `C1A_CANDIDATE_LINEAGE.json` records parent → candidate, gate result
  (`allowed=true`, effective allowlist
  `["object:INSERT_OBJECT_CROSSWALK"]`), run id, producer.

## C1.5 Determinism + idempotency

- Build A and Build B (two fresh writer runs from the semantic parent):
  `C1D_DETERMINISM.json` — `identical=true`,
  build_a == build_b == `16ea2c…d11f`.
- Self-rerun of the writer over the build-A output (`C1E_IDEMPOTENCY.json`):
  `rerun_written=0`, `rerun_skipped_existing=66`,
  SHA unchanged after rerun → adds 0 new semantics.

## C1.2 Crossing ledger (C1B)

- 179 authoritative crossings (identical to the accepted S07 set), all
  dispositions accounted (INSERTED 61, DUPLICATE_MERGED 5,
  AMBIGUOUS_MATCH_REJECTED 78, OUTSIDE_MAP_SCOPE 35).
- `within_limit=true` (≤179), `accounting_invariant=true`.
- 66 of them map to `crosswalk_{osm_id}` objects in the candidate with
  non-empty `<outline><cornerLocal u v z>` (C1F
  `crosswalk_corners`: 66/66 non-empty, 0 empty).

## C3 Pedestrian ledger (C1C)

- 5431 pedestrian source ways re-ledgered (same extractor and
  classification as stage_j):
  - classification: CROSSING 179, FOOTWAY 2719, PATH 1954,
    PEDESTRIAN_STREET 78, PLATFORM 103, SIDEWALK 398.
  - dispositions: ALREADY_PRESENT 5071, INSERTED_XODR_OBJECT 66,
    PACKAGE_MESH_REQUIRED 181, OUTSIDE_MAP_SCOPE 35,
    AMBIGUOUS_REJECTED 78.
  - footway/path→sidewalk lane: no lane writes occur; candidate keeps
    the XODR sidewalk lane network untouched. No footway/path→driving
    lane, no silent drops (accounting_invariant=true).

## C4 Protected-integrity recompute (C1F)

- Structural digests (v1 6 categories + combined) recomputed on the
  candidate and compared with the frozen S04 authority:
  `combined_structural_digest_unchanged=true`; all category flags true.
- Traffic-control digests (v2) unchanged: combined, signal_element,
  signal_reference, controller.
- Signal id set unchanged (parent 3467 == candidate 3467).
- Semantic inventory delta: ONLY `objects`+`crosswalk_objects` changed and
  delta exact (66 expected ids); no provisional artifacts.

## Freeze

- freeze_schema: `C1R_TAG_ANCHORED_V2`
- freeze_tag: `c1_freeze_20260809T000000Z_C1`
- parent_commit: the pre-C1 carrying commit (C0 freeze commit
  `38e0522c`… legacy is the C0R tag; C1 parent = HEAD before the C1
  freeze commit).
- NO head_commit, NO freeze_commit, NO tag-object sha recorded in any
  committed JSON (non-circular freeze; the annotated tag carries the
  identity).
- review invariant: no commits allowed after tag creation before
  Claude's C1 review; worktree clean; tag points at terminal C1 commit.