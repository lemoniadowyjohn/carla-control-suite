# R13F — Crosswalk object lemma applied: real candidate coordinates (R13G/R13J)

*Status: COMPLETE — evidence produced by `stage_r13_production.py` (R13 batch,
run `20260808T000000Z_C0_REMEDIATION`).*

## 1. Purpose

Proves that the real crosswalk `<object>` records in
`candidate_crosswalk_enriched.xodr` satisfy the CARLA 0.9.16 schema lemma
(`docs/R05_CARLA_0916_CROSSWALK_OBJECT_SCHEMA.md`) and provides fixture-grade
coordinates for every real crosswalk plus coverage guarantees.

## 2. Lemma requirements applied (per R05)

- `type="crosswalk"` (exact); id `crosswalk_{osm_id}`; `name` = subtype.
- Corners ONLY as `<outline><cornerLocal u v z>` — `cornerGlobal` is ignored
  by ObjectParser (empty point list) and MUST be absent.
- Attaches to the hosting road via `road_id`; `s` / `t` / `hdg` attributes.

## 3. R13J XML object count (real candidate)

| Metric | Value |
| --- | --- |
| `crosswalk` objects | 66 |
| unique ids | 66 (one per OSM crossing way) |
| `cornerLocal` total | 348 (closed polylines, 4..5 corners per record) |
| `cornerGlobal` total | **0** (lemma-satisfying; nothing silently dropped) |
| verdict | `XML_OBJECT_COUNT_VERIFIED` |

The 66 = the Stage I.1 written set (66 of 179 crossings authored; the rest
disposed as outside-scope / ambiguous / duplicate-merged per Stage H).

## 4. R13G fixture rows

`R13G_CROSSWALK_COORDINATE_FIXTURES.csv` — 69 rows: 66 REAL (from the
candidate) + synthetic fallbacks only when coverage lacked a case.

Columns: `fixture_id, osm_id, source, road_id, s, t, hdg_deg, orientation,
position, context, cornerLocal`.

Coverage guarantees (all verified in `tests/test_r13_evidence.py`):
orientation N/E/S/W; position CENTER/SIDE; context STRAIGHT/JUNCTION/
ROUNDABOUT; every fixture has a parseable cornerLocal polyline; ids unique.

Context derivation: `JUNCTION` = road appears in a `<junction><connection>`
in/out; `ROUNDABOUT` = closed-loop road geometry (end point within 5 m of
start); else `STRAIGHT`. This is the exact repair-scope context of the
phase-E roundabout/junction hardening.

## 5. Usage note

These fixtures are **evidence-only** — they do not change the candidate.
No C1 load payload is generated in this batch. Any future CARLA spawn fixture
authoring must reuse the exact cornerLocal set from the candidate bytes (never
re-derive from OSM), because `Map::GetAllCrosswalkZones` transforms exactly
these stored points into world polygons.