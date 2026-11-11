# SCI-CORRECT-003 acceptance review (2026-11-04)

**Verdict: `REQUIRES_CORRECTION`.**

**Independence caveat:** this review was done by the same agent (Claude Opus 5.5) that wrote the
packages under review. It is a **mechanical author verification**: every path, hash and number was
re-executed against its source. It is **not** the independent acceptance that the packages' own
checklist requires (a reviewer from a different model family). Even after the corrections below are
applied, `ACCEPTED_FOR_DOCS_PUBLICATION` requires that external review.

Reviewed:
- `reviews/SCI_CORRECT003_20261104/` (12 files);
- `reviews/SCI_ARCH001_20261104/`;
- `reviews/ARCH003_20261104/`.

Baseline: `1a36b560a69286841d4c42973cf00258a38f56c1`.

## 1. Verified as correct (re-executed)

| # | Check | Result | Command / source |
|---|---|---|---|
| V1 | The 2026-10-07 run is XODR reprocessing | **OK.** `run_manifest.json` `inputs.INPUT_XODR.sha256 = 370abbbb…`; `sha256(01_sanitized) = 370abbbb…` | manifest read; `sha256sum` |
| V2 | GAP-079 source attribution | **OK.** `UNKNOWN_PENDING_RAW_OSM_REPRODUCTION` in the addendum-3 draft | JSON read |
| V3 | GAP-080 is unique and OPEN | **OK.** No GAP-080+ in `*.json`/`*.md` on any local or origin ref; status open | `git grep` over all refs |
| V4 | GAP-080 numbers | **OK.** 3,947 / 3,696 (> 0.5 m) / 3,716 (> 10°); median 0.7467 m / 26.565°; p95 1.458 m / 50.9°, all equal to `evidence/lcc_off_v2.json`; labelled LOCAL_REPRODUCED, with a second implementation required | JSON read |
| V5 | GAP-070 stays open and separates containment from correction | **OK** (but see D7) | JSON read |
| V6 | Stage-3 / stage-5 identity | **OK.** `_copy_artifact(elev_out, geo_out)` at `stage_06_links.py:296` @ `22cf39ab` (exact line); `sha256(03) = sha256(05) = 45c52059…`; receipt `mode = READ_ONLY_DIAGNOSTIC` | `git show`, `sha256sum` |
| V7 | RQ2 values | **OK.** hull 0.0597 / 0.2206 / W 0.0752 / ratio 2.683; bbox 0.0614 / 0.2248 / W 0.0743 / ratio 4.488 / 6,076 roads; whole map 0.0415 / 0.0931; hull crop 143,606.1 / 53,525.3 m, 3,536 / 993 | `local_registration.json` |
| V8 | RQ4 values | **OK.** seeds 0.905 / 0.775 / 0.967 / 0.963 / 0.994; mean 0.9207; CI [0.845, 0.976]; std 0.088; superseded 0.6434 [0.616, 0.676] (`C21_REPORT.md:71`; `rq_tables.json` `superseded_value`, sha256 `e66a4552…`) | JSON + report read |
| V9 | RQ4 map pair hashes | **OK, and upgraded:** `manual_grid0821.xodr` sha256 `69ee3498e0e7ca74…`; `candidate_connectivity_repaired.xodr` `c3dc29d3f570d929…` at `reports/ingolstadt_map_quality_v2/work_package_02_connectivity/` | `sha256sum` (local) |
| V10 | Historical artifacts unchanged | **OK.** `git diff 1a36b560 -- reports docs configs` is empty; addendum 2 is `5f59fc60…`; `RQ_ANSWERS_20261104.md` is `a59f337f…`; the freezes are `5aa8ae24…` / `db7155fe…` | `git diff`, `sha256sum` |
| V11 | Ledger | **OK in count:** 24 rows, 24 unique ids (C01–C15, G01–G09) | csv read |
| V12 | Addendum-3 reproducibility | **OK.** The builder regenerates the JSON byte-identically; register 25 / 19 / 5 / 1 | `cmp` |
| V13 | RQ3 / RQ5 | **OK.** NOT_MEASURED / DEFERRED; no numbers anywhere | grep |

## 2. Discrepancies → see `DISCREPANCIES.csv`

Three are major (D1–D3) and must be fixed before any publication. Eight are minor (D4–D11).

## 3. Exchangeability assessment of the RQ4 design (D2, in detail)

The draft statistic is `T = mean_b d(a_b, m_b) − mean_{b≠b'} d(m_b, m_b')`, with a per-block
auto/manual label swap.

1. **The first term is invariant under the permutation.** Cosine distance is symmetric, so swapping
   the two labels of block b leaves `d(a_b, m_b)` unchanged. The permutation then varies only the
   within-"manual" term, and the test does not measure cross-domain separation as intended.
   **Fix:** use a two-sample statistic that is sensitive to label swaps. Examples:
   - an energy distance / MMD between the sets {a_b} and {m_b}:
     `mean_{b≠b'} d(a_b, m_b') − ½[mean d(a_b, a_b') + mean d(m_b, m_b')]`;
   - the held-out accuracy of a domain-label probe.
   Use the paired per-block swap as the permutation for either.
2. **Blocking does not create independence.** Independent per-block swaps are exact only if, under
   H0, the auto/manual labels are **conditionally exchangeable per block, independently across
   blocks**. That is stronger than the natural H0 "the two map-generation processes are equal in
   distribution", which justifies only joint swaps. It fails when:
   - roads and junctions cross block borders, so neighbouring tile embeddings share content;
   - the manual author's conventions vary smoothly over space;
   - the GNN's receptive field spans blocks.

   **Fix:**
   - (a) a buffer: drop tiles within the GNN receptive-field radius of block borders;
   - (b) restricted permutations that swap **clusters** of adjacent blocks jointly, as a sensitivity
     analysis;
   - (c) report results across ≥ 3 block sizes B, with B pre-registered as the primary;
   - (d) a pilot variogram of the block-level statistic, to choose B.
3. **Inference scope:** with one region and one map per domain, the p-value is **conditional on this
   region's realization**. It tests internal structure, not a population of map pairs. The draft says
   this for population claims (§10), but should also state it next to the test.
4. **The historical thesis test** (K=1000 permutation, p<0.001; `THESIS_TO_CURRENT_PROGRESS.md:14`)
   is undocumented in its unit and statistic, and predates the 2026-09-01 graph-builder fix and the
   GAP-010 leak fix. It is REPORTED_NOT_REPRODUCED and does not apply to the 0.921 retrain. See D1.

## 4. Separation of facts, findings and hypotheses (current state)

- **Historical facts (GITHUB_VERIFIED):** the RQ2 JSON values; the RQ4 JSON values; the C15
  summary; the addendum-2 text; the code at `22cf39ab` / `1a36b560`.
- **Locally reproduced findings:** the input lineage; the stage identity; the lane-centre counts
  (GAP-070 / GAP-080); the stub counts.
- **Hypotheses (must be labelled as such; see D10):**
  - "systematic template geometry" (inferred from the tight IQR);
  - "authoring conventions may explain the count ratios";
  - "the training width mode was legacy" (inferred from defaults).

## 5. Publication readiness

Not ready:
- D3: the citations would break, and 3 of the 5 review folders are missing from the C0 staging;
- D1 and D2 are scientific corrections;
- an external reviewer is required.
