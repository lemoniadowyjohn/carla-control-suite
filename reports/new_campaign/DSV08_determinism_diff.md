# DSV08 — Conversion Determinism Semantic-Diff (run1 vs run2)

**Model:** DeepSeek V4 Light · **Mode:** READ-ONLY (compare only; no repair) · **Task ID:** DSV09-LEDGER batch
**Branch:** `integration/governed-map-quality-20260729` · **Base SHA:** `7506128da4e3bd56e0bb8a010cb0abd03f7ab7d0`
**Verdict:** `CONVERSION_DETERMINISTIC`

## 1. Files compared (both LFS-materialized, 82,318,841 B)

| Run | Path | sha256 |
|---|---|---|
| run1 (A) | `candidate/raw_xodr_run_1.xodr` | `6044a87d8d6e116b444fe4413a46ab97085033def004b62d011233f4ddc0e93d` |
| run2 (B) | `candidate/raw_xodr_run_2.xodr` | `c8c57c7282f483592802307aa9ccc839eedf1468279690afa612b0bcd59734c2` |

Byte-different (as expected), identical byte size.

## 2. Header differences (the ONLY differences found) — non-semantic

- XML comment: `<!-- generated on 2026-07-31 11:38:06 by ...` vs `...11:38:21 by ...` (identical configuration block after the timestamp)
- `<header>` `date`: `Fri Jul 31 11:38:06 2026` vs `Fri Jul 31 11:38:21 2026`
- Identical: `revMajor=1 revMinor=4 name="" version=1.00`, north/south/east/west bounds, `geoReference` (`+proj=tmerc` in both)
- **Classification: non-semantic (run timestamp only)**

## 3. Structural comparison (excluding `<header>`)

- Canonical tree (tag + sorted attrs + stripped text + children in document order): **EQUAL**
- Ordering-only check: N/A — document-order trees already identical
- Differing element paths: **0** (diff_record_count = 0)

## 4. Element tag census — identical for all 27 tags

| tag | count | | tag | count |
|---|---|---|---|---|
| road | 32,710 | | junction | 3,646 |
| connection | 22,816 | | lane | 84,781 |
| laneLink | 32,040 | | link | 117,483 |
| predecessor | 64,738 | | successor | 64,692 |
| planView | 32,710 | | geometry | 80,261 (line 26,220 / paramPoly3 54,041) |
| elevation / elevationProfile / laneSection | 32,710 each | | roadMark | 84,781 |
| width/speed | 52,071 | | signals | 22,816 |
| type | 32,710 | | center/right/lateralProfile/objects/laneOffset | 32,710/32,710/32,710/32,710/3,562 |
| OpenDRIVE/header/geoReference | 1 | | | |

No count difference anywhere → no semantic count difference.

## 5. Independent canonical semantic hash

- A == B == `138e6aab2b5a23a9a254ee58c75d3d7deed6199f54b7f0aa3cefa4a79e774a1d`
- Does NOT equal manifest `semantic_sha256 019fc30e...` → **algorithm-not-replicated** (the manifest's exact JSON shaping is not derivable from its one-line description). Tree-equality (step 3) is the primary proof; the manifest hash remains authoritative for its own algorithm.

## 6. Verdict

**CONVERSION_DETERMINISTIC**: the two runs are byte-different ONLY in the header timestamp/comment (15 s apart), and are SEMANTICALLY IDENTICAL in every structural respect. The C55V01a "≥2 identical runs" claim is PROVEN.

Audit trail: temp script `C:\Users\admin\AppData\Local\Temp\opencode\xodr_semantic_diff.py` + `...\xodr_semantic_diff_result.json` (outside the repo; nothing modified inside the repo).
