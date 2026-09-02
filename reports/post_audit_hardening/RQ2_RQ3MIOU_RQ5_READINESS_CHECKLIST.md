# RQ2 / RQ3-mIoU / RQ5 readiness checklist

WS4 of the map-quality/RQ hardening plan (2026-09-02). All infrastructure below is
code-complete and tested where CARLA-independence allows it (confirmed by this session's
research agents and direct code inspection). Nothing here is new code — this is the exact
command sequence to run, in order, the moment the CARLA GPU-TDR livelock is confirmed resolved.
Do not skip step 1; do not attempt step 2 until step 1 passes clean.

## 0. Context — what's blocked and why

- **RQ2** (perceptual domain gap) and **RQ3-mIoU** (segmentation IoU comparison): zero evidence,
  blocked purely on the CARLA GPU-TDR livelock (chronic `LiveKernelEvent 141`, root-caused in
  `reports/post_audit_hardening/C20_GPU_TDR_20260821/FINDINGS.md`). Not a code defect — every
  piece of capture/training/eval infrastructure is present and tested.
- **RQ5** (real-world generalization) has two independent blockers: (a) no trained model
  checkpoint exists anywhere on this machine — itself gated behind the same livelock, since a
  checkpoint requires trained on CARLA-captured synthetic data; (b) no real-world Ingolstadt
  dataset has been acquired (out of scope per prior explicit user decision — not addressed here).
- RQ2 additionally needs both maps (manual + auto) cooked in Unreal for a genuinely unconfounded
  comparison. Unreal cook automation is explicitly out of scope (zero UE Editor API / cook-CLI
  code exists anywhere in the repo, confirmed this session) — RQ2 may need to proceed with a
  documented confound/caveat, or wait on that separate, larger effort. That decision is not
  made here.

## 1. GPU-TDR preflight (fast, seconds — always run this first)

```
python -c "from ultimate_pipeline.core.gpu_tdr_preflight import windows_gpu_tdr_preflight_from_env as p; import json; print(json.dumps(p(), indent=2))"
```

Check `"ok": true` and `"reason": "no_recent_livekernelevent_141"` in the output. If `"ok":
false`, the TDR stream has not actually stopped — do not proceed to step 2; treat as the driver
fix not yet resolved (see `RUNTIME_GUARD.md` in the same C20 report directory for the full
operator runbook). Env-tunable: `UP_CARLA_TDR_LOOKBACK_HOURS` (default 24), `UP_CARLA_TDR_MAX_EVENTS`
(default 0 — any recent event blocks).

## 2. Minimal CARLA connectivity probe (before a full map load)

```
python scripts/opendrive_gen_probe.py
```

Launches its own throwaway CARLA server, generates a tiny procedural MINI_XODR world, and reports
a verdict to `reports/post_audit_hardening/OPENDDRIVE_GEN_PROBE/`. This is cheap and fast relative
to loading the real ~85 MB pinned map — if this hangs the same way the full pipeline used to,
the livelock is not actually resolved regardless of what step 1 reported. Only proceed past this
step if it completes with a clean verdict.

Optionally also verify reachability against a running server directly:
```
python -m ultimate_pipeline.tools.carla_preflight --host 127.0.0.1 --port 2000 --out <out-dir> --timeout 10
```

## 3. Perception capture

```
python -m ultimate_pipeline.perception.dataset_generator \
  --calib <path/to/calib_data.json> \
  --all-cameras \
  --frames 200 \
  --label-mode semantic \
  --out-root <datasets-root> \
  --map-type auto \
  --xodr <path/to/final/xodr> \
  --host 127.0.0.1 --port 2000
```
Repeat with `--map-type manual` (and the manual reference map/xodr) to get both sides of the
comparison. `--label-mode semantic` is required for training/mIoU; `none` only captures RGB.
Verify output layout matches `rgb/<camera>/*.png` + `semseg_raw/<camera>/*.png` per camera (the
C8-hardened, no-empty-labels layout).

## 4. Train the segmentation model

```
python -m ultimate_pipeline.perception.train_launcher \
  --dataset <captured-dataset-root> \
  --camera front_left_camera \
  --out-dir <training-out-dir> \
  --epochs 30
```
FCN-ResNet50, class-weighted loss, `Any(255)` sentinel correctly ignored (C27 fix). Produces
`<out-dir>/checkpoints/model_last.pt` (exact filename per `train_launcher.py`'s own output —
confirm in its printed summary rather than assuming). This checkpoint is also what RQ5 needs.

## 5. RQ3-mIoU evaluation (labeled simulator data)

```
python -m ultimate_pipeline.perception.eval_sim_labeled \
  --model <out-dir>/checkpoints/model_last.pt \
  --dataset <captured-dataset-root> \
  --camera front_left_camera \
  --out-json <out-dir>/sim_labeled_eval.json
```
Run once against the auto-map capture and once against the manual-map capture. Their two
`--out-json` outputs are the `PERCEPTION_AUTO_JSON`/`PERCEPTION_MANUAL_JSON` inputs for step 6.

## 6. RQ2 domain-gap evaluation (feeds into the main RQ1/RQ2 pipeline)

Set `PERCEPTION_MANUAL_JSON`/`PERCEPTION_AUTO_JSON` (env or `ultimate_pipeline/config/settings.py`)
to the two `eval_sim_labeled.py` outputs from step 5, then run the existing domain-gap driver
(`ultimate_pipeline/run_full_domain_gap.py`) as normal — it already has a
`perception_manual_json`/`perception_auto_json` code path (gated behind the `perception` domain-gap
category being enabled) that consumes them via `PerceptionEvaluator.load_metrics`. This is the
same entrypoint `stage_12_domain_gap.py` calls in the live pipeline — no new script needed.

## 7. RQ5 evaluation (once/if a real-world dataset is separately supplied)

```
python -m ultimate_pipeline.perception.eval_real_unlabeled \
  --model <out-dir>/checkpoints/model_last.pt \
  --real-dir <real-world-images-dir> \
  --out-json <out-dir>/real_eval_report.json \
  --sim-dataset <captured-dataset-root> \
  --sim-camera front_left_camera
```
`--real-dir` recursively finds `.png/.jpg/.jpeg/.bmp` in any structure, no labels/manifest needed
(~100-500+ images recommended per the existing docstring). `--sim-dataset` is optional but
recommended — enables the FID-like distance metric against the simulator distribution.

## 8. Fold new evidence into the thesis bundle

```
python tools/run_c19_assembly.py [--out-dir <path, default reports/post_audit_hardening/C19_THESIS_ASSEMBLY>]
```
Runs `export_thesis_tables` → `audit_thesis_topic_contract` → `validate_thesis_claim_provenance` →
`pack_thesis_run`, fail-closed at the first failing step. Regenerates `rq_tables.json` with the
new RQ2/RQ3-mIoU/RQ5 rows no longer `DEFERRED`.

## Verification note

Every command above was checked against the actual current `argparse` definitions in this
session (not recalled from memory) — see git history for this file if any script's CLI has since
changed. No runtime verification of this checklist was possible (needs live CARLA), so treat step
1-2's own output as the first real signal something has changed, not this document.
