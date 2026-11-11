# OpenCode — remaining implementation prompt (2026-10-23, supersedes the older OpenCode files)

Paste everything below the line into an OpenCode session running the default **build** agent. It
dispatches `@implementer`, then `@reviewer` (→ `reviewer_alt` → `reviewer_alt2`), by name.

---

## ROLE AND STATE

You coordinate the remaining OpenCode tasks under `AGENTS.md`. You never write code yourself: one
`@implementer` at a time, then one `@reviewer` per commit.

- Worktree: `E:/wt/repair-map-realism-p0-837a8504`
- Branch: `experimental/verified-fixes-20261022`, HEAD `1953107d` (verify it)
- Already committed and independently re-checked: O0–O7, O2 and the C1 addendum (10 commits since
  `1e902986`). Do NOT redo them.
- **Parallel writer:** Codex/Claude works at the same time in `E:/wt/claude-hard-tasks-20261023`. Never
  touch that directory. **You must not edit these files:** `rq3_evidence_gate.py`,
  `record_route_fixed.py`, `test_rq3_artifact_content_verification.py`, `test_rq3_review_receipt_binding.py`,
  `core/file_utils.py`, `core/atomic_io.py`, `stage_04_enrichment.py`, `stage_06_links.py`,
  `stage_07_lanes.py`, `stage_09_positional_semantics.py`, `access_restriction_metadata.py`,
  `lanes/lanelink_builder.py`. Your earlier commits to `rq3_evidence_gate.py` and
  `test_rq3_artifact_content_verification.py` are superseded by the Claude branch when the operator merges.
  Leave them as they are.

## HARD RULES (paste to every subagent)

1. Forbidden: push, merge, rebase, reset, stash, checkout of other branches, branch deletion, editing
   `configs/rq3_protocol_freeze_v1.json` / `configs/rq5_protocol_freeze_v1.json`, editing anything under
   `reports/`, changing map pins or the registry, regenerating or promoting maps, starting CARLA.
   Only `git add` / `git commit` are allowed.
2. Set `GIT_LFS_SKIP_SMUDGE=1`. Disk E: has about 3.5 GB free: no large files, no LFS downloads.
3. Preserve EOL and BOM (`core.autocrlf=false`; check `file <path>` before and after). Per commit,
   `git diff -w --ignore-cr-at-eol --stat HEAD~1 HEAD` must equal `git diff --stat HEAD~1 HEAD`.
4. Write the regression test first in `ultimate_pipeline/tests/unit/`. Run it on the unfixed code and
   paste the failing tail. Scratch scripts in the repo root are not tests and must not be committed.
5. Python: `C:/Users/admin/PycharmProjects/gpt4/pythonProject3/.venv/Scripts/python.exe`; pytest with
   `-p no:cacheprovider`. Never weaken an assertion. No PASS or COMPLETE without a commit SHA, the
   pasted output and a reviewer APPROVE.
6. One commit per task, with message `<prefix> (<ID>)`.

## TASKS (in order)

**B1 — `is_main` used before assignment (P0, live on production).**
- `ultimate_pipeline/perception/train_launcher.py` reads `is_main` at line 437 and assigns it at 441, so
  every training run crashes with `UnboundLocalError`.
- Fix: move `ddp_enabled, rank, world_size = _init_ddp(args.ddp)` and `is_main = (rank == 0)` above the
  `if is_main: _revoke_stale_success(out_dir)` block. Change nothing else.
- Test: monkeypatch `enforce_dataset_acceptance` → `{"accepted": True, "total_paired_frames": 1}` and
  `_init_ddp` → `(False, 0, 1)`; raise a sentinel exception right after `_revoke_stale_success` (or at
  model build) so no training runs; call `main()` with `--dataset <tmp> --out-dir <tmp>/out`.
- Assert: no `UnboundLocalError`, and a pre-existing `<out>/SUCCESS.txt` is removed.
- Commit `fix(rq5): is_main ordering (B1)`.

**B2 — random-init backbone.**
- In torchvision 0.24.1, `fcn_resnet50(weights=None)` still loads `ResNet50_Weights.IMAGENET1K_V1`.
  Both frozen protocols say "random initialization; no pretraining".
- Add `weights_backbone=None` at `train_launcher.py:309`, `min_train_segmentation.py:207`,
  `eval_sim_labeled.py:237` and `eval_real_unlabeled.py:290`.
- `rq5_provenance.verify_random_initialisation` currently writes the literal
  `"weights_backbone_argument": None`. Give it keyword parameters `weights` and `weights_backbone`, record
  the OBSERVED values, and raise `PretrainingContractError` if either is not None. Update its callers.
- Test: monkeypatch `torchvision.models._api.WeightsEnum.get_state_dict` to raise; building through each
  factory must not call it. `verify_random_initialisation(model, weights=None,
  weights_backbone=ResNet50_Weights.IMAGENET1K_V1)` must raise.
- Report (do not edit) any file under `reports/`, `campaigns/` or `datasets/` that claims
  `weights_backbone_argument: null` or `random_frozen_protocol`.
- Commit `fix(rq5): explicit random-init backbone + honest pretraining receipt (B2)`.

**B3 — `--contract` silent fallback.**
- `tools/rq5_contract_audit.py:63-69`: `audit(repo, contract)` falls back to `DEFAULT_CONTRACT` when an
  explicitly given `contract` path does not exist.
- Fix: an explicit but missing path returns `status: "FAIL"` with a row whose evidence contains
  `missing_contract_path:<path>`, with no fallback. The fallback stays only for `contract is None`.
- Tests: explicit missing → FAIL; explicit existing → `contract_path` equals it; None → default.
- Commit `fix(rq5): no silent fallback for explicit --contract (B3)`.

**L1 — make the P0-B orphan road repair safe**
(`ultimate_pipeline/topology/orphan_road_repair.py`, `ultimate_pipeline/pipeline_stages/stage_03_topology_repair.py`).

Audit-reproduced defects:
1. `_road_endpoints` applies `math.radians()` to an OpenDRIVE heading that is already in radians. A
   north road of 100 m from (0,0) gets end (100.0, 2.7) instead of (0, 100). Arcs with ~0 curvature do
   `hdg += length`. paramPoly3 and spiral are treated as lines.
2. It always writes `<successor>`, even when the orphan's START matched.
3. It never writes `contactPoint`.
4. It writes no reciprocal link on the target.
5. It may target junction-internal roads.
6. It has no heading or elevation check: a parallel road 20 m away gets linked.
7. Stage 3 swallows exceptions as "non-fatal", and the default `UP_ORPHAN_SNAP_M` is 25.0 while the
   docstring says 5.0.

Fix:
- Use `ultimate_pipeline.geometry.opendrive_geometry_kernel.endpoint` (and the start pose) for all
  primitive types.
- Write `predecessor` if the orphan's start matched and `successor` if its end matched. Set
  `contactPoint` from the target endpoint ("start"/"end").
- Write the reciprocal link on the target. If that target slot is already occupied, do not link; record
  the residual reason `target_endpoint_occupied`.
- Never target a road with `junction != "-1"`.
- Require direction-aware heading continuity within `ORPHAN_MAX_HEADING_DEG = 30` and |Δz| within
  `ORPHAN_MAX_DZ_M = 1.0`. Use the elevation profile when present. Put both values in settings as named
  constants; the operator signs them off. Never tune them to reduce residuals.
- Default snap: 5.0 m. Under `THESIS_STRICT`, any `UP_ORPHAN_SNAP_M` above 5.0 raises.
- Under `THESIS_STRICT`, exceptions propagate.
- Report every created link (orphan, endpoint, target, contactPoint, distance, Δheading, Δz) and every
  residual with its reason.

Tests (each must fail first): north-road endpoint; start-match → predecessor + contactPoint + reciprocal;
parallel road 20 m away → not linked; junction-internal target refused; occupied slot refused;
paramPoly3 endpoint correct. Do NOT regenerate or promote any map.
Commit `fix(topology): safe orphan repair (L1)`.

**L2 — a missing road-link `contactPoint` is a defect, not "start".**
- In `enrichment/lane_successor_topology.py`, `fixes/fix_missing_lane_successors.py` and
  `quality/check_lane_connectivity.py`, every `get("contactPoint", "start")` on a road-type link must
  stop defaulting. Skip inference through such a link and report it as
  `road_link_contactpoint_missing`.
- New validation-only `quality/check_road_link_reciprocity.py`:
  - every road→road link has a contactPoint;
  - if A's successor/predecessor is road B at B's start or end, then B's link at that end points back to
    A, or the pair is junction-mediated.
  - Wire it into `pipeline_stages/stage_08_integrity.py` as a report. It is a gate only under
    `THESIS_STRICT`.
- Tests: missing contactPoint; asymmetric pair; valid pair; junction-mediated pair.
- Then run the check read-only on
  `C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/reports/rq1_trial_runs/run_01/20261007_214826_524342/07_lanes_20261007_214826_524342.xodr`
  and report the counts. Record the file's sha256 before and after; it must not change.
- Commit `fix(topology): contactPoint required + reciprocity check (L2)`.

**T1 — reproduce production CI (`@test_triage`, read-only).** Read `.github/workflows/tests.yml` at
`d72f57c6`. List its jobs and steps and the exact pytest command, then run that command on HEAD. Classify
each failure as product, environment (Windows vs Linux, or un-smudged LFS) or pre-existing. No installs.

**D1 — final check (`@reviewer`, read-only).**
- Bare `pytest -p no:cacheprovider -q` on a clean tree. Report exact counts; LFS-pointer failures are
  `INCOMPLETE`, not PASS.
- Freeze hashes at HEAD: rq3 `5aa8ae248b26ed1bcc053ae1b70b5a508e3fd05b5cab4bb68debc495f44b98bd`,
  rq5 `db7155fef00787ee615767f309df0247248381e18911d571741bbfa1030fcb8d`.
- `git log 1e902986..HEAD --stat`: no `reports/` edits, no file over 5 MiB.

## REVIEW LOOP

After every implementer commit, send it to `@reviewer`:

> "Review commit <sha> (task <ID>) read-only. Re-run the gate yourself. Try ≥3 inputs the implementer did
> not test. Check that only the allowed files changed, with no EOL churn. Check the freeze hashes. Return
> APPROVE or REJECT with commands and output."

On REJECT, do one fix round, then review again. After a second REJECT, write
`CODEX_HANDOFF_<ID>_20261023.md` (untracked) and move on. On quota errors, use the fallback chain; if all
three agents fail, the task is NOT_RUN.

## FINAL OUTPUT

A table with one row per task (B1, B2, B3, L1, L2, T1, D1): commit SHA, reviewer verdict, test counts,
status. Then the HEAD SHA and the freeze hashes. Never write COMPLETE without a SHA plus APPROVE.
