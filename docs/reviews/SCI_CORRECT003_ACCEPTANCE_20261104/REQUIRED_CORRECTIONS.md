# Required corrections, in order

These are drafts only. Every edit goes into the **review drafts**, never into committed files.
Rebuild the derived files and their hashes after each step.

1. **D1 (RQ4 null):** in all four places, replace "no null was computed" with:
   > "A thesis-era K=1000 permutation test (p<0.001) is reported in
   > `docs/research/THESIS_TO_CURRENT_PROGRESS.md:14` (REPORTED_NOT_REPRODUCED; its unit and
   > statistic are undocumented). It predates the 2026-09-01 graph-builder fix and the GAP-010 leak
   > fix, so it does not apply to the 0.921 leak-free retrain, for which no null exists."

   Add a ledger row, `C16`.
2. **D2 (RQ4 spec):**
   - replace the statistic with a swap-sensitive two-sample statistic (energy distance / MMD between
     the block-embedding sets, or the held-out domain-probe accuracy);
   - keep the paired per-block swap;
   - add a border buffer equal to the receptive-field radius, cluster-restricted permutation as
     sensitivity, ≥ 3 block sizes, and a variogram pilot;
   - state next to the test that inference is conditional on this region.
3. **D3 (citations):**
   - decide the published layout: `docs/reviews/ARCH_X8_X9_20261104/`,
     `docs/reviews/ARCH002_20261104/`, `docs/reviews/ARCH003_20261104/`,
     `docs/reviews/SCI_ARCH001_20261104/`, `docs/reviews/SCI_CORRECT003_20261104/`;
   - rewrite the citations in the drafts to those paths, adding each folder's `SHA256SUMS` hash;
   - update the constants in `build_addendum3.py` and rebuild the addendum-3 JSON;
   - restage C0 with all five folders and re-run the dry-run add, the path scan and `SHA256SUMS`.
4. **D7:** reword GAP-070 part (c) so the containment evidence is the snap-OFF arm, and C1 is
   "proposed, uncommitted".
5. **D4, D5, D6, D10, D11:** small text and CSV fixes (see `DISCREPANCIES.csv`).
6. **D8 and D9:** add a new evidence subfolder with:
   - the three arms re-run with the saved script;
   - synthetic positive and negative controls for the lane-centre method.
   Keep the old outputs.
7. **External acceptance:** a reviewer from a different model family runs
   `SCI_CORRECT003_20261104/INDEPENDENT_ACCEPTANCE_CHECKLIST.md` plus this report's checks V1–V13.
8. **Operator:** approve publication as a docs-only branch.
