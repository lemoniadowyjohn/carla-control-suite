# Corrections applied after the acceptance review (2026-11-04)

The acceptance report, `DISCREPANCIES.csv` and `REQUIRED_CORRECTIONS.md` in this folder are kept
**as written at review time**. Their `reviews/…` paths describe the state that was reviewed. This
file records what was changed afterwards. Every change was made in the review drafts; no committed
file was changed.

| ID | Applied | Where | Verification |
|---|---|---|---|
| D1 | The thesis-era K=1000 permutation test (p<0.001) is recorded as REPORTED_NOT_REPRODUCED and not applicable to 0.921; "no null" is now scoped to the leak-free retrain | `SCI_CORRECT003/RQ_ANSWERS_REVISED_DRAFT.md` (RQ4); `CLAIM_EVIDENCE_LEDGER.csv` (C12 updated, **C16 added**); `SCI_ARCH001/SCIENTIFIC_CLAIM_BOUNDARIES.md` (RQ4) | text read back |
| D2 | Statistic replaced by an energy distance (the paired-swap-invariant T withdrawn); exchangeability conditions, border buffer, cluster-restricted permutation, block-size sensitivity, variogram pilot and region-conditional scope added; checklist updated | `SCI_CORRECT003/RQ4_STATISTICAL_EVALUATION_SPEC.md` §2, §3, §5, §11 | text read back |
| D3 | All citations rewritten to publish paths `docs/reviews/<package>/` (18 rewrites in drafts; measurement outputs untouched); addendum 3 cites leaf evidence files by sha256; C0 restaged with every package as a sibling folder | all review folders; `evidence/build_addendum3.py` | regex scan finds no `reviews/<package>` outside `docs/reviews/`; dry-run `git add` |
| D4 | G09 provenance_class set to `LOCAL_REPRODUCED` (detail moved to the note); the ledger now uses only the 5-value vocabulary | `CLAIM_EVIDENCE_LEDGER.csv` | script check: 0 out-of-vocabulary rows (25 rows) |
| D5 | Full sha256 values and the corrected path for Grid0821 and candidate_connectivity_repaired; class `LOCAL_REPRODUCED` | `SCI_ARCH001/INPUT_IDENTITY_AND_PROVENANCE_MATRIX.csv` | `sha256sum`: `69ee3498…72c42e8`, `c3dc29d3…995a7ca43` |
| D6 | U-turn connectors (3,949, `uturn_count.py`) and U-turn laneLinks (3,947, GAP-080) cited separately | `RQ_ANSWERS_REVISED_DRAFT.md` (RQ2) | text read back |
| D7 | GAP-070 (c): containment evidence is the snap-OFF arm; C1 is described as "PROPOSED, UNCOMMITTED, NOT REVIEWED" and not relied on | `evidence/build_addendum3.py` → addendum 3 JSON | rebuilt |
| D8 | All three arms re-run with the saved script into `ARCH003/evidence/rerun_20261104/` (the originals are kept). Totals and snap reports are **identical** for off, merged and candidate | `ARCH003/evidence/rerun_20261104/` | comparison script: True / True / True |
| D9 | Synthetic controls added: A (continuous) 0 m / 0°; B (reference line on the incoming reference line) 3.25 m; C (rotated atan ½) **0.7467 m / 26.565°**, which exactly reproduces the real U-turn median | `ARCH003/evidence/controls/` | results JSON |
| D10 | Hypotheses prefixed "Hypothesis (untested)" or "(inferred from defaults, unrecorded)": template geometry (GAP-080), authoring conventions (RQ2), legacy width mode (RQ4) | addendum 3; `RQ_ANSWERS_REVISED_DRAFT.md`; `SCI_ARCH001/SCIENTIFIC_CLAIM_BOUNDARIES.md` | text read back |
| D11 | GAP-id search repeated over **all 808 refs, all text files except map/raster/model data**; no hits | addendum 3 `id_allocation_check` | see `D11_GAP_ID_SEARCH.txt` |

Independence: these corrections were made by the authoring agent. External review (a different
model family) is still required before `ACCEPTED_FOR_DOCS_PUBLICATION`.
