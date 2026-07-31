# DSV07 — Reconcile the DSV05 Measurement Identity

**Model:** DeepSeek V4 Light · **Mode:** READ-ONLY · **Task ID:** DSV09-LEDGER batch
**Branch:** `integration/governed-map-quality-20260729` · **Base SHA:** `7506128da4e3bd56e0bb8a010cb0abd03f7ab7d0`
**Verdict:** `MEASUREMENT_RECONCILED`

## 1. Which file was measured in DSV05

- DSV05 ran `check_post_tiling_integrity.py` against:
  `campaigns/ingolstadt_cooked_perception_v1/candidate/raw_xodr_run_1_epsg32632_header_pinned.xodr`
- LFS oid: **`ff2a05e7b00b8fc1bde38f569413223c03a4f4ac9c31eceb5a8592df47d0d17d`** (82,318,919 B) — the RAW authoritative candidate, NOT a tiled derivative.
- Campaign dir inventory (fresh): contains exactly the 3 raw candidates + manifests; **no tile/ dirs, no tiled XODR derivatives anywhere**.

## 2. Counting method (tool source, `check_post_tiling_integrity.py:50-68`)

```python
tree = ET.parse(xodr_path); root = tree.getroot()
roads = root.findall("road");        report["num_roads"] = len(roads)
junctions = root.findall("junction"); report["num_junctions"] = len(junctions)
signals = root.findall(".//signal");  report["num_signals"] = len(signals)
```

→ `num_roads`/`num_junctions` are **logical OpenDRIVE `<road>` / `<junction>` element counts** of the input file. No tiling, no segmentation, no splitting. (The tool's name says "post-tiling", but it counts whatever file it is given; given the raw candidate it counted raw logical records.)

## 3. Manifest expected counts

| Source | road_count | junction_count |
|---|---|---|
| `manifest.json` `candidate_xodr` (L57-58) | 32,710 | 3,646 |
| `manifest.json` `raw_xodr_runs[0]` (L264-265) | 32,710 | 3,646 |
| `manifest.json` `raw_xodr_runs[1]` (L470-471) | 32,710 | 3,646 |
| `candidate/manifest.json` (L13-14, 220-221, 426-427) | 32,710 | 3,646 |
| `agent_sync.yaml` (L26-27) | 32,710 | 3,646 |
| **DSV05 measured** | **32,710** | **3,646** |

**Exact match: manifest == DSV05 == DSV08 independent count (road 32710 / junction 3646).**

## 4. Where the ~5,539 came from

The ~5,539 figure is from **different artifacts** in DSV02's donor matrix — the JSNAP-processed legacy thesis map:
- `08_final_rerun3_BEST_jsnap.xodr`: 5,539 roads / 677 junctions / 19,149,977 B (codex-jsnap)

That is the OLD structural-gap/JSNAP lineage (also `auto_aligned_rigid` 5,837 roads, `08_final_structural_gap` 5,712 roads) — legacy thesis maps, NOT the new CARLA Osm2Odr conversion of the full Ingolstadt study OSM (74,874 nodes → 32,710 logical roads, road IDs in 39xxx range per control points).

## 5. Plain statement

32,710 is the **logical `<road>` element count** of the authoritative raw XODR `ff2a05e7` — consistent with the campaign manifest everywhere it is recorded, and independently corroborated by DSV08's tag census (road 32710 / junction 3646 / connection 22816 / lane 84781). The 6× gap vs ~5,539 is **artifact lineage** (new raw full-conversion vs legacy JSNAP-processed donor), NOT a measurement artifact.

**C55V01b must validate against 32,710 roads / 3,646 junctions / 22,816 connections (manifest-bound), not ~5,539.**
