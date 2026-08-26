# C27 — perception chain offline readiness: DONE, 3 real bugs found and fixed

All 4 modules audited with TDD, fully offline (mocked CARLA / synthetic data), no live CARLA
dependency. **This was not a clean pass** — chasing the spec'd "Any=255 handling" checklist item
surfaced a real, previously-latent bug class that touched 3 of the 4 modules, ranging from a
metric-correctness issue to a training-crash.

## Root finding: `carla.CityObjectLabel.Any == 255` was never actually usable

Verified directly against the installed `carla` package: `Any = 255` is CARLA's real, common
sentinel for unclassified/miscellaneous pixels (sky, distant unclassified geometry — present in
essentially every real capture). `CARLA_SEMANTIC_MAX_CLASS_ID = 28` (named classes only). This gap
was never caught because **CARLA has been broken all session** (chronic GPU watchdog TDR, see
C20), so this code path was only ever exercised with synthetic test fixtures that happened to
never include `255`. The moment a real capture is attempted, this would have surfaced immediately.

## Findings, in the order the chain would hit them

1. **`capture_writer.py` (via `carla_classes.assert_label_ids_in_range`) — capture-blocking crash.**
   Any frame containing an Any pixel would raise `ValueError` on write. Fixed: 255 now explicitly
   allowed alongside 0–28; true corruption (e.g. 200) still fails closed. 4 tests
   (`test_perception_any_255.py`).
2. **`eval_sim_labeled.py` — silently wrong metric, not a crash.** `_compute_iou_per_class`
   accidentally excluded Any (its `range(num_classes)` loop never reaches 255) so mIoU was safe by
   luck, but `_compute_pixel_accuracy` counted every pixel — since a 29-class model head can never
   predict 255, every Any pixel was an unavoidable, meaningless miss, systematically deflating
   reported accuracy. Fixed: `ignore_index` param added and wired into the real call site. 5 tests
   on known confusion matrices (`test_eval_sim_labeled_metrics.py`).
3. **`min_train_segmentation.py` — training-crash, most severe.** `CrossEntropyLoss(weight=...)`
   had no `ignore_index`; PyTorch requires targets in `[0, num_classes)` or the configured ignore
   value — training would crash on the first real batch containing an Any pixel. Fixed. 4 tests
   incl. a real end-to-end training step (`SegDataset` → `fcn_resnet50` → backward → `opt.step()`)
   on a tiny on-disk synthetic dataset containing Any pixels (`test_min_train_segmentation_any_255.py`).
   Also checked `class_weights.scan_label_class_counts` for the same exposure — already safe
   (`np.bincount` sliced to `[:num_classes]`, silently and correctly drops 255).
4. **`eval_real_unlabeled.py` — verified correct, no fix needed.** Operates purely on RGB images +
   model output logits; never loads a label, so it's not exposed to this bug class at all. 6
   known-value tests (entropy near-0/near-max, Fréchet ~0 for identical distributions and
   positive+monotone for a mean shift) plus a real end-to-end run all pass immediately
   (`test_eval_real_unlabeled.py`).

## Collateral: 3 pre-existing tests corrected
`test_carla_classes.py`, `test_class_weights.py`, `test_semantic_class_policy.py` each specifically
asserted `255` was invalid — true under the old (buggy) policy, factually wrong now. Updated to use
a genuinely-invalid value (200) for the rejection case, with an explicit "accepts 255" assertion
added alongside each, preserving original intent.

## Claim boundary
These are readiness/contract tests on synthetic + a tiny real-model pass — they prove the chain
**runs correctly**, not that any RQ result exists. RQ2/RQ3 still need real captures, gated on the
GPU driver fix (C20). But without this pass, the *first* real capture attempt after CARLA is fixed
would have hit the crash in finding #1 immediately, and any completed training run would have hit
finding #3.

## Verification
643/643 full unit suite green. 19 new tests across 5 files, all TDD (RED→GREEN where a bug was
found; written-and-passing where verifying existing correctness).
