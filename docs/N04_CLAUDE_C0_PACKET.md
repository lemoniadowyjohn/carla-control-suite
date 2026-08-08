# N04 — Claude C0 Packet: Semantic Write Contract (Stage 4 hard stop)

> **Execution stage: 4 of 20. HARD STOP — no semantic mutation until Claude returns `CLAUDE_SEMANTIC_WRITE_CONTRACT_ACCEPTED`.**
> Produced by: OpenCode (laguna-s-2.1-free). Review order: OpenCode → N04 → Claude C0 → OpenCode continue → C1.
> This packet is evidence-first: every hash/count below is recomputed from primary
> files in this session (none trusted from prior reports).

---

## 1. Semantic parent (frozen, read-only)

| field | value |
|---|---|
| **path** | `reports/post_audit_hardening/20260807T000000Z/candidate_g_semantic_enriched.xodr` |
| **name** | `candidate_g_semantic_enriched` |
| **sha256_lf_text (canonical)** | `d604ac393e12730ed276f5c865d0ef82c8a537b97bd8d79beeddd4c96863e470` |
| **schema/v** | OpenDRIVE 1.6 (via `osgb` header) |

### Structural counts (recomputed, in-session)

| roads | junctions | laneSections | lanes | roadMarks | signals | objects | controllers | signalReferences |
|---|---|---|---|---|---|---|---|---|
| **32710** | **3646** | **32710** | 84781 | 84781 | **3467** | 0 | 0 | 0 |

All match the campaign contract. `verdict = SEMANTIC_PARENT_FROZEN`.

### Parent (repaired candidate)

| field | value |
|---|---|
| path | `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_fixed_final.xodr` |
| sha256_raw_bytes | `80ebb0054afd73ffdd51960b48679ff4689c72ed0abe75af5b2ae10a51395699` (matches reported repaired SHA ✓) |
| sha256_lf_text | `516e329cb6fcec6adb041a4c5f39c48b4de6147b956c7dc2b7ab0c6746490453` |
| signals | **0** (negative control: this is NOT the semantic parent) |

### Descendant / structure preservation (hard stop gate)

`descended_from_repaired = structure_preserved = True`. All six protected structural
digests are **byte-identical** between repaired parent and semantic parent:

| digest | value (identical) |
|---|---|
| PLANVIEW_DIGEST | `e4b4402a2644e2905410d34d083d6255dbfc47fd29068ff93eac333f6b49f06a` |
| ROAD_LINK_DIGEST | `645f1a8fdc2e77f0e52e7727fc6daa0fc97bab564ab7c618bc4ce390c1183975` |
| JUNCTION_DIGEST | `ba65c039e348dcb5e6fdc9ee370327ccab132d232fcf7263ac1da7ef92aae6d6` |
| LANELINK_DIGEST | `fcfad5c3ced7f66350ab41bab4a6784f3459c4ac1dedbc6d4f54c8775d13a662` |
| LANESECTION_DIGEST | `31c8e0447ef70bef60f84393e739d703ea7da7e6785b9b133d27276087ae8c56` |
| ELEVATION_DIGEST | `18618e75687e32edb8030fc3b9c686d10d3aaa1b000442f4f97ea99cf5af8291` |

`combined_structural_digest = b30d96781ea61d5822e24c5eb6812048cc98b9c82f70357f5b9e65c67b3a8353`.
Protected-digest canonical source: `phase_q/structural_digest.py` (schema `phase_q/structural_digest/v1`).

### Traffic-control digests (N03/S05) — canonical source: `phase_q/signal_digest.py`

| digest | value |
|---|---|
| schema / version | `phase_q/signal_digest/v1` / 1.4 |
| COMBINED_TRAFFIC_CONTROL_DIGEST | `393ddad4861370ffd126da28bd1cd8416adf039eac1163d9d3e5772566dbf1c5` |
| SIGNAL_ELEMENT_DIGEST | `0ac4a46686227999fb0bbdb4d264b4d2cdc2312195efff7d4e039a1ac35e8df1` |
| signal count | 3467 |
| signal_reference_count | 0 |
| SIGNAL_REFERENCE_DIGEST | `5feceb66ffc86f38d952786c6d696c79c2dbc239dd4e91b46729d73a27fb57e9` |
| controller_count | 0 |
| CONTROLLER_DIGEST | `5feceb66ffc86f38d952786c6d696c79c2dbc239dd4e91b46729d73a27fb57e9` |

The signal element digest covers per-signal: id, road id, s, t, type, subtype,
orientation, dynamic, country/type metadata, value/unit, validity lane ranges,
signalReferences, and controller relationships (see `phase_q/signal_digest.py`).

### Accepted connector repairs (12) — verified preserved

Road IDs: `50003, 51425, 51646, 52738, 54261, 56874, 57300, 58404, 62170,
66369, 68135, 69106`. Repair method (`worktrees/phase-e-hardening/fix_junction_connectors.py`):
`set geometry length = road length` for the sole zero-length connector geometry
(road_length 0.0 → patched to positive). Detected against the raw source
`campaigns/.../candidate/raw_xodr_run_1_epsg32632_header_pinned.xodr`.

---

## 2. Target platform

**CARLA version: 0.9.16** — canonical exe `E:\CARLA\CARLA_0.9.16\CarlaUE4.exe`,
build hash `0.9.16-win64` (`ultimate_pipeline/config/settings.py:675`).
Unreal 4.26 (CARLA 0.9.16). The runtime server is currently **BLOCKED** for live
validation (B4 toolchain blocker per `generate_audit.py:24`); crosswalk
`<object>` authoring targets the offline parse + `phase_L` runtime path, but the
final `PERCEPTION_READY`/`FULL_PRODUCTION_RELEASE` verdict remains blocked by
toolchain availability. Offline evidence gates only.

---

## 3. Reuse capability matrix (N00 = `S02_REUSE_CAPABILITY_MATRIX.csv`)

Produced by canonical `stage_0_provenance.py`. Statuses:

| capability | status | canonical evidence |
|---|---|---|
| signal_digest / fingerprint | REUSE_UNCHANGED | `phase_q/signal_digest.py` (N03 schema) |
| semantic_inventory | REUSE_UNCHANGED | `phase_q/semantic_evidence.py` |
| osm_crossing_extraction | REUSE_UNCHANGED | `ultimate_pipeline/tools/phase_h0_osm_signal_extract.py` |
| osm_road_matching | REUSE_UNCHANGED | `ultimate_pipeline/tools/phase_h1_osm_road_match.py` |
| signal_writing | REUSE_UNCHANGED | `ultimate_pipeline/tools/phase_h2_signal_writer.py` |
| **crosswalk_writing** | **NO_EXISTING_CAPABILITY** | *(gap — see §5)* |
| object_writing | REUSE_UNCHANGED | `building_extruder.py:110-119`, `object_injector.py:137-145`, `regulatory_sign_writer.py` |
| pedestrian_classification | REUSE_UNCHANGED | `phase_q/actor_binding.py`, `phase_q/label_ontology.py:49`, `phase_q/semantic_evidence.py` |
| sidewalk_writing | REUSE_UNCHANGED | `enrichment/sidewalk_builder.py` |
| provenance_userdata | REUSE_UNCHANGED | `enrichment/sidewalk_builder.py`, `markings_builder.py` |
| semantic_replay / idempotency | REUSE_UNCHANGED | `phase_h2_signal_writer.py` (remove-legacy idempotent writer pattern) |
| candidate_governance / payload | REUSE_UNCHANGED | `phase_q/governed_payload.py` |
| manifest_generation | REUSE_UNCHANGED | `phase_q/governed_payload.py` |
| integrity_audit | REUSE_UNCHANGED | `ultimate_pipeline/tools/phase_h3_signal_integrity.py` |
| xodr_structual_validation | REUSE_UNCHANGED | `quality/check_carla_opendrive_compat.py`, `quality/quality_gates.py`, `tools/preflight_xodr_loadability.py` |

**Conclusion:** crosswalk authoring has NO existing capability. It must extend
the existing `object_writing` pattern (`<object>` + `<outline>/<cornerGlobal>`,
as in `building_extruder.py:110` and `object_injector.py:141`) — NOT a
parallel writer. Post-mutation integrity reuses `phase_q/structural_digest.py`
and `phase_q/signal_digest.py` directly (deterministic re-digest + compare).

---

## 4. OSM authority (recomputed, N05; in-session)

`stage_0` recompute (S03) + Stage H authority ledger (S07/S08):

| metric | recomputed value | reported claim | status |
|---|---|---|---|
| OSM crossing ways | **179** | ≈174 | STALE — 179 is authoritative |
| OSM crossing nodes | 0 | — | — |
| OSM crossing total | **179** | — | matches Stage H disposition total |
| OSM footway/path ways | 5247 | ≈78 | STALE — reported figure was stale |
| OSM pedestrian areas | 35 | — | — |

Stage H disposition ledger (authoritative crossings = 179, invariant 179==179):

| disposition | count |
|---|---|
| INSERTED | 61 |
| DUPLICATE_MERGED | 5 |
| OUTSIDE_MAP_SCOPE | 35 |
| AMBIGUOUS_MATCH_REJECTED | 78 |
| ALREADY_PRESENT | 0 |
| UNSUPPORTED_GEOMETRY / SOURCE_INVALID | 0 |

→ Net crosswalk mutation delta = **+66 `<object type="crosswalk">`** (61 INSERTED
new + 5 DUPLICATE_MERGED merged onto primary road). 113 remain rejected and
ledgered with reasons (fail-closed, no disappearance — A1).

### Sample authoritative crossings (from Stage H S07)

```
osm_id=26677871  way   highway=footway  crossing=traffic_signals  nodes=2
osm_id=168243635 way   highway=footway  crossing=unmarked         nodes=3
osm_id=175770994 way   highway=footway  crossing=marked           nodes=3
```

### Sample authority row (INSERTED), osm_id=317613599
`highway=footway crossing=traffic_signals s=18.903 t=-3.0 road=70396
centroid=[839005.059,5467952.77] length_m=25.269 nodes=6
match_distance_m=7.41 reason="matched road=70396 s=18.903 t=-3.0 dist=7.41"`

### Sample DUPLICATE_MERGED (multi-road), osm_id=317613600
`road_ids=["70382","70396"] s=25.536 t=-4.4 dist=12.294 reason="matched to 2 roads: ['70382','70396']"`

### Sample pedestrian OSM features (recompute, 5 samples)

```
WAY osm_id=22715565 highway=path               nodes=17  (pedestrian path)
WAY osm_id=23011316 highway=path               nodes=12  (pedestrian path)
WAY osm_id=23036978 highway=footway            nodes=5   (footway)
WAY osm_id=...(area) highway=primary area=yes nodes=N   (pedestrian area, pedestrian=yes tag)
NODE osm_id=...(crossing) highway=crossing crossing=zebra  (crossing node)
```

Classification scheme (reuse `phase_q/label_ontology.py:49`, `phase_q/actor_binding.py`):
`SIDEWALK | FOOTWAY | PEDESTRIAN_STREET | CROSSING | PATH | PLATFORM | ACCESS_ONLY | UNSUPPORTED`.

---

## 5. Proposed CARLA/OpenDRIVE representation

### 5.1 Crosswalk `<object>` (extend `object_injector.ObjectInjector._attach_object`)

Reuse the existing write schema verbatim (`object_injector.py:120-145`,
`building_extruder.py:110-119`):

```xml
<object id="crosswalk_{osm_id}" type="crosswalk" name="{subtype}"
        s="{s:.3f}" t="{t:.3f}" zOffset="0.00"
        hdg="{polyline_bearing_deg:.3f}" roll="0.0" pitch="0.0"
        orientation="none" height="0.00" dynamic="no">
  <outline>
    <cornerGlobal x="{x:.3f}" y="{y:.3f}" z="0.000"/>  <!-- 5 corners: closed quad -->
  </outline>
</object>
```

Field sourcing (all from Stage H authority row):

| XODR attr | source | rule |
|---|---|---|
| `type` | literal | `"crosswalk"` (required — Q6/Q7 `_crosswalks_from_xodr` filters on it) |
| `name` | `_crossing_type_subtype(crossing_type)` | `traffic_signals`→`crosswalk_signals`, `marked`→`crosswalk_marked`, `unmarked`→`crosswalk`, `zebra`→`crosswalk_zebra` |
| `id` | `crosswalk_{osm_id}` | deterministic, idempotent (osm_id globally unique) |
| `road_id` (parent) | `road_ids[0]` | primary matched road from authority |
| `s`,`t` | authority `s`,`t` | exact placement (e.g. s=18.903, t=-3.0) |
| `hdg` | bearing(start_m→end_m) | crossing polyline bearing (across-road) |
| `zOffset` | literal | `0.00` (road-surface marking) |
| `height` | literal | `0.00` (planar) |
| `outline` | `_quad_outline(start_m,end_m, depth=4.0)` | closed quad, CCW, 5 vertices |

**Multi-road (DUPLICATE_MERGED, 5 rows):** option **B — primary road + trace.**
Emit on `road_ids[0]`, record all `road_ids` in mutation ledger provenance.
Rationale: additive, no cross-road object (invalid in OpenDRIVE), A1 preserved
(crossing not dropped), traceable. The alternate road gets no object this stage.

> Claude review item (5.1a): confirm option B (primary+trace) over option A
> (split the crossing into per-road objects). Default assumed B unless objected.

### 5.2 Pedestrian representation (proposed)

NOT auto-converting footways to lanes (directive). Pedestrian authority will be
classified into `INSERTED_XODR_OBJECT` (crosswalk `<object>` already handled in
5.1) and `NAVMESH_ONLY` / `PACKAGE_MESH_REQUIRED` for footways. Detailed lane
semantics deferred to Claude C1 review.

---

## 6. Proposed mutation allowlist (strict — additive only)

Allowed to change between N01 (semantic parent) and the first enriched candidate:
- ADD `<object type="crosswalk">` children under existing `<road><objects>` (66 total).
- ADD corresponding `<objects>` element containers where missing.

**Everything else MUST be byte-stable** (re-verified via N02/N03 digests):
- roads, junctions, planView, road links, LaneLinks, laneSections, elevation,
  superelevation/crossfall, road marks, signals, signalReferences, controllers,
  the 12 connector repairs.

Negative control T01: `ingolstadt_fixed_final.xodr` (signals=0) must be REJECTED
as a semantic parent → `HARD FAIL` (missing 3467-signal layer).

Parent hard gate before any write:
`semantic_parent SHA == d604ac393e12730ed276f5c865d0ef8...` AND
`signals==3467` AND `roads==32710` AND `junctions==3646` AND
`COMBINED_TRAFFIC_CONTROL_DIGEST==393ddad4…` AND
`PLANVIEW_DIGEST==e4b4402a…` AND `CONNECTOR_REPAIR_DIGEST` (==12 ids).

---

## 7. Proposed provenance format

Each inserted crosswalk object carries provenance via the mutation ledger
(N09). Per-directive provenance attributes on `<object>`:
`name` (carries subtype + classification), and a `<userData>` per road with
`<crosswalk_origin osm_id="..." source="ingolstadt_authoritative.osm"
source_sha="..." disposition="..." />`. Reuse `provenance_userdata` pattern
(S02 REUSE_UNCHANGED: `markings_builder.py`, `sidewalk_builder.py`).

---

## 8. Proposed integrity gates (post-write, reuse canonical validators)

Re-run deterministic (N02/N03 digests + Stage L count):
1. `roads==32710`, `junctions==3646`, `signals==3467` unchanged.
2. `signal ID set` unchanged; `SIGNAL_REFERENCE_DIGEST` unchanged;
   `CONTROLLER_DIGEST` unchanged.
3. `PLANVIEW_DIGEST`, `ROAD_LINK_DIGEST`, `JUNCTION_DIGEST`, `LANELINK_DIGEST`,
   `LANESECTION_DIGEST`, `ELEVATION_DIGEST`, `COMBINED_STRUCTURAL_DIGEST`,
   `COMBINED_TRAFFIC_CONTROL_DIGEST` all UNCHANGED (N10).
4. `existing_crosswalk_object_ids_in_xodr == 66` (Stage H re-run).
5. Phase L (runtime, when 0.9.16 available): `m.get_crosswalks() == 66`
   (`phase_l_validation.py:272`).
6. Q6/Q7 fail-closed gate: `crosswalk_total == 66`,
   `verdict == ACTOR_BINDING_VERIFIED` (needs runtime actors; offline: `crosswalk_total==66`).
7. Determinism (N15): re-run from frozen parent twice → identical SHA + digests.
8. Idempotency (N16): re-enrich h1 → `crosswalk_objects_written == 0` new,
   same canonical hash, same protected digests.

Canonical validators to reuse:
`xodr_strict_opendrive` (`core/carla_opendrive_loader.py`),
`check_carla_opendrive_compat` (`quality/`),
`quality_gates.py` (schema/range gate),
`preflight_xodr_loadability.py`,
`phase_h3_signal_integrity.py` (integrity_audit).

---

## 9. Tests to be implemented (T08–T19 map)

- T08 ambiguous crossing rejected (→ AMBIGUOUS_MATCH_REJECTED, not written)
- T09 crossing s out of bounds rejected (→ AMBIGUOUS_MATCH_REJECTED)
- T10 malformed polygon rejected (self-intersecting quad → skip + ledger)
- T11 crossing authority fully accounted (179 == sum(dispositions))
- T12 pedestrian authority fully accounted
- T13 unsupported pedestrian feature not auto-written
- T14 planView mutation rejected (digest unchanged)
- T15 road/junction mutation rejected
- T16 LaneLink mutation rejected
- T17 connector-repair mutation rejected (12 ids stable)
- T18 deterministic two-run output (SHA identical)
- T19 idempotent re-run (0 new insertions)

---

## 10. Artifacts produced in this batch (Stage 1–4)

All in `reports/post_audit_hardening/20260807T000000Z/`:
- N00 = `S02_REUSE_CAPABILITY_MATRIX.csv` (stage_0_provenance.py)
- N01 = `S03_SEMANTIC_PARENT_AUTHORITY.json` (stage_1_freeze_semantic_parent.py)
- N02 = `S04_PROTECTED_STRUCTURAL_DIGESTS.json` (stage_1)
- N03 = `S05_TRAFFIC_CONTROL_DIGESTS.json` (stage_1)
- N05 = `S03_OSM_CROSSING_AUTHORITY_RECOMPUTE.json` + Stage H `S07/S08/S09`
- N04 = this packet

**Status: STOPPED at Stage 4.** Awaiting `CLAUDE_SEMANTIC_WRITE_CONTRACT_ACCEPTED`.
