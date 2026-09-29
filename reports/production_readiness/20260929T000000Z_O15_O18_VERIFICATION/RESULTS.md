# Independent verification of O15-O18 (branch o20-failure-recovery-resume-audit)

Scope: verification only, per task instructions. Nothing merged; no fixes applied on this
branch. Work done in an isolated worktree (`G:/audit-worktrees/o20-verify-20260929`) off
`origin/o20-failure-recovery-resume-audit` @ `a189c1e6` (the protectively-committed checkpoint).

## Headline finding (all four items below trace back to this)

**The MainPipeline object crashes unconditionally on any real pipeline run reaching STEP 4,
on this branch, right now.** Reproduced live in this session (see "Fresh spot-check" below):

```
[2026-09-29 04:59:33] ❌ PIPELINE CRASHED: 'MainPipeline' object has no attribute '_step4_semantic_source_preparation'
AttributeError: 'MainPipeline' object has no attribute '_step4_semantic_source_preparation'
...
Only 0 successful runs.
```

Root cause (confirmed by reading `ultimate_pipeline/main_pipeline.py` at this branch's HEAD,
lines 4378-4384): `_step4_semantic_source_preparation` (and `_step9_positional_semantics`,
line 4577) are defined at module level (column-0 `def`), **dedented out of `class
MainPipeline:`**, while every call site uses bound-method syntax
(`self._step4_semantic_source_preparation(...)`). Any run reaching STEP 4 crashes
identically regardless of input.

This is a real, already-known, already-fixed bug: **GAP-027** ("critical MainPipeline dedent
crash (P0, fixed)"), fixed at commit `4ddb7ced` (2026-09-24 06:04:19+0200) and logged into
`MASTER_GAP_REGISTER.json` at commit `ddf85b5a` (2026-09-24 12:36:37+0200) — **both several
hours before O15 was committed (14:36:26+0200) the same day.** Neither commit is an ancestor
of this branch's HEAD (`git merge-base --is-ancestor 4ddb7ced HEAD` → NO). The fix lives on
sibling integration lineages (`integration-oc39-20260923`, `fix/ci-closure-blender-writerlock-20260924`,
several `docs/phase*-20260924` branches, `hardening/v5-incremental-20260929`) that this
`o20-failure-recovery-resume-audit` branch never merged.

**Correction to the task's premise:** GAP-027 does *not* appear in
`reports/production_readiness/20260918T000000Z_PRODUCTION_CLOSURE/MASTER_GAP_REGISTER.json`
on this branch — that file here only goes up to GAP-026 (confirmed: 548 lines, last entry
GAP-026, `update_note` mentions "the full 26-issue set"). The GAP-027 entry exists only on
the branches where `ddf85b5a` landed, which this branch does not contain. So the task's
instruction to "read GAP-027's entry" in that exact file, on this exact branch, cannot be
fulfilled as stated — the entry is real and correctly described (critical MainPipeline crash,
fixed) but is simply absent from this branch's copy of the register. This is itself evidence
of the same root problem: this O-series branch is missing recent fix-and-log commits.

## O15 — "RQ1 five-run determinism matrix" (`fac400c5`)

**Verdict: commit title is misleading; the artifact it produced is honest and says the
opposite of what the title implies.**

`git show fac400c5` adds three files: `tools/rq1_five_run_matrix.py` (a comparison tool that
*would* build a pass/fail matrix given 5 real run receipts), its unit tests (4 tests, all
using synthetic in-memory JSON fixtures, no real pipeline involved), and
`RQ1_FULL_DETERMINISM_MATRIX.json` — the actual output artifact. That artifact's full content:

```json
{
  "reason": "five isolated run receipts required, got 0",
  "run_count": 0,
  "runs": [],
  "status": "INCOMPLETE",
  "verdict": "INCOMPLETE"
}
```

**0 runs, not 5.** `git log --oneline -- RQ1_FULL_DETERMINISM_MATRIX.json` shows exactly one
commit ever touched this file (`fac400c5` itself) — it has never been regenerated with real
data since. This is fully consistent with, not a correction of, the prior attempt the task
describes as having "timed out with 0 successful runs": that attempt is documented in
`reports/production_readiness/20260924T120000Z_RQ1_RQ4_MASTER_CLOSE/RESULTS.md` (generated
2026-09-24T12:00:00Z, ~36 minutes before O15's commit), which records two full-OSM-bootstrap
determinism-harness runs at 2400s timeout each, both timing out with 0 successful runs, and
concludes verdict `RQ1_BOUNDED_POST08_UNEXERCISED` — explicitly *not* a 5-run pass. The GAP-027
fix commit itself (`4ddb7ced`, same day, earlier) says outright: "RQ1's own coverage-extension
goal remains genuinely incomplete (the harness run timed out, 0 successful complete runs) --
this fix removes one blocker found along the way, it does not itself close that gap."

So: **no, the evidence does not show 5 genuinely successful, complete, isolated runs.** It
shows 0. O15 built real, reasonable comparison tooling (the matrix-building logic itself is
correct and fail-closed — non-normalized unknown fields, structural-signature mismatch
correctly flagged FAIL, `<5` receipts correctly flagged INCOMPLETE) but never had real data to
feed it, and the checked-in artifact says so plainly. The commit *message* ("RQ1 five-run
determinism matrix") is the only place a false impression of completion could come from; the
artifact and code are honest.

### Fresh spot-check (this session, real execution, not mocked)

Reproduced the same cheap single-tile-fixture harness used by the 2026-09-23 reverification
(`reports/production_readiness/20260923_RQ1_REVERIFICATION/RESULTS.md`), in the isolated
worktree, fully fresh:

```
UP_INPUT_XODR=reports/post_audit_hardening/20260804T060000Z/tiles/tile_1_0.xodr
UP_OSM_FILE=reports/rq1_reverify_smoke_20260923/fixture.osm
python -m ultimate_pipeline.run_determinism_audit --runs 2 --offline-only --timeout-per-run 500 --seed 42
```

Result: **both runs crashed identically** at STEP 4 with the GAP-027 `AttributeError` above
(exit code 2, "Only 0 successful runs"). This is a *worse* failure than the 2026-09-23 report
(which reached stage 08 before hitting a legitimate correctness gate) — confirming this
branch has regressed relative to the lineage where GAP-027 was fixed, and that **no
determinism evidence of any kind can currently be produced on this branch** until that fix (or
an equivalent) is merged in.

## O16 — "RQ3 pairing preflight tool" (`f08d9b11` + `dc62419c`)

**Verdict: partial/weaker than the stated contract, with a real fail-open gap.**

`tools/rq3_pairing_preflight.py`'s `REQUIRED_SHARED` list is reasonably comprehensive on
paper — it covers CARLA version (`carla_server_version`), sensor rig
(`sensor_rig`/`sensor_transforms`/`camera_intrinsics`/`lidar_parameters`), weather, timing
(`synchronous_mode`/`fixed_delta`/`frame_count`/`warm_up`), seed, route policy
(`route_definition`), class map (`class_map`), and capture protocol (`exclusion_policy`).

**The fail-open gap:** the tool takes three separate dicts — `manual`, `automatic`, `shared`
— and only *presence*-checks `REQUIRED_SHARED` fields against `shared` (an apparently-separate
"declared contract" input, not either side's actual capture record). The manual-vs-automatic
*mismatch* check only fires for a field when `field in manual and field in automatic` — if a
required field is simply absent from **both** the manual and the automatic capture manifests
(as opposed to the `shared` file), no mismatch is ever flagged, and nothing else requires
`manual`/`automatic` to actually carry these 14 fields. A pairing where neither side ever
recorded, say, `seed` or `sensor_transforms` in its own manifest — but the separate `shared`
file happens to declare them — passes cleanly.

This gap is real and untested: every test in `tests/unit/test_o16_rq3_pairing_preflight.py`
uses a `_world()` helper that only ever populates `expected_map_identity` /
`expected_map_hash` / `expected_map_version` / `available_in_runtime` on the manual/automatic
dicts — **none of the 14 `REQUIRED_SHARED` fields are ever present on either side in any
test.** So the core "does the automatic capture actually match the manual capture on CARLA
version / sensor rig / seed / weather / etc." comparison is dead code: it is structurally
never exercised by the test suite (since `field in manual` is always False for those 14
fields), and `test_matching_contract_passes_without_starting_capture` "passes" trivially,
not because parity was verified.

## O17 — "RQ3 dataset manifest verifier" (`4ad1ee08`)

**Verdict: same class of fail-open gap, and it is explicitly exercised as a *passing* test
case rather than flagged as incomplete.**

`tools/rq3_dataset_manifest_verifier.py::verify(manifest, paired=None)` — the cross-manifest
pairing comparison (`route_id`/`weather_identity`/`seed`/`carla_version`/
`sensor_transform_identity`/`class_map_version`) only runs `if paired is not None`. Calling
`verify()` with no second manifest (the CLI's `--paired` is optional, defaulting to `None`)
skips the entire pairing check and returns `status: PASS` (given a self-consistent single
manifest) with `paired_contract_mismatches: []`, indistinguishable in the `status` field from
a real, checked pairing pass. There is no separate `pairing_performed` flag.

`tests/unit/test_o17_rq3_dataset_manifest_verifier.py::test_valid_manifest_passes` calls
`verify(_manifest())` with no `paired` argument and asserts `status == "PASS"` — i.e. the test
suite treats "pairing check was never run" as a legitimate green result, not as
INCOMPLETE/BLOCKED. `test_paired_contract_mismatch_fails` does show the mismatch detection
itself works correctly when a paired manifest *is* supplied — so the comparison logic is
sound, only the "no second manifest supplied" default path is fail-open.

## O18 — "RQ5 experiment contract static audit" (`36ffcf1b`)

**Verdict: does not implement, and is not about, the RQ5(b) claim-boundary rule the task
asked to check.** No fail-open pattern relative to that rule, because the rule isn't
addressed at all.

The established rule (from `docs/research/THESIS_TO_CURRENT_PROGRESS.md`'s RQ5 row): "Unlabeled
distribution shift/CORAL/MMD protocol checks are not model-generalization accuracy, and no
manual-target training result may be relabeled as generated-to-manual transfer" — i.e. RQ5(b)
real-world claims must stay in unlabeled/shift language, not accuracy/mIoU language, absent
labeled real-world data.

`tools/rq5_contract_audit.py` does something orthogonal: it greps three files
(`ultimate_pipeline/config/settings.py`, `ultimate_pipeline/experiments/thesis/
exp_osm_to_xodr_determinism.py` — note: this is the **RQ1** determinism experiment script, an
odd choice for an "RQ5 experiment contract" audit — and `README.md`) for loose keyword
presence (`model_architecture` → checks if `"model"` or `"architecture"` appear *anywhere* in
the concatenated text) against a checklist of generic ML-experiment-design decisions
(architecture, splits, learning rate, epochs, optimizer, etc.). Nothing in `REQUIRED`,
the keyword logic, or the output schema mentions "unlabeled," "labeled," "accuracy," "mIoU,"
"CORAL," "MMD," or "real-world" — the specific claim-boundary vocabulary this program has
established as the RQ5(b) rule. I also checked the one place in the repo that *does* encode an
RQ5 metric allow-list, `ultimate_pipeline/config/thesis_rq_contract.py`
(`RQ_ALLOWED_METRICS[RQ5]`): it lists both accuracy/mIoU-style metrics
(`generated_train_manual_test_accuracy`, `mIoU_transfer_degradation`,
`miou_auto_train_manual_eval`) and unlabeled-shift metrics
(`real_unlabeled_shift_metrics`, `domain_adaptation_coral_mmd`) as equally "allowed RQ5 tags" —
it does not restrict RQ5(b) specifically to the unlabeled subset either. So this specific
claim-boundary rule currently has **no automated enforcement anywhere found in this branch**;
O18 is a different, unrelated audit (generic experiment-design-decision completeness) that
happens to also be tagged "RQ5."

Separately, by construction `audit()` never emits status `"DEFINED"` for any row (only
`"AMBIGUOUS"` or `"MISSING"`), so the overall `status` can never be `"PASS"` — this leans
fail-closed rather than fail-open, but it also means the tool cannot currently distinguish "a
decision truly is undocumented" from "a decision is documented but this audit's classifier
just can't tell" (the AMBIGUOUS bucket absorbs almost everything due to the weak
substring-keyword match).

## RQ4_SEED_RECOVERY.json cross-check

**Verdict: genuine discrepancy, flagged per task instructions rather than assumed
consistent.**

`RQ4_SEED_RECOVERY.json` (root-level, generated_at_utc `2026-09-24T16:00:00Z`) reports:
`summary` all-zero (`complete_valid: 0`, ... `missing: 0` despite `possible_states.MISSING`
being annotated "(CURRENT STATE)"), `evidence_note`: "Five-seed leak-free RQ4 extension not
found in local workspace... found only deterministic seed=42 runs, not five distinct seeds,"
and `recommendation`: "Retraining required to obtain five-seed leak-free RQ4 extension. Do not
reuse pre-leakage-fix results."

This directly conflicts with `reports/production_readiness/20260924T120000Z_RQ1_RQ4_MASTER_CLOSE/
RQ4_MASTER_CLOSE_VERIFICATION.json` — **present in this same branch's tree**, generated
`2026-09-24T12:00:00Z`, i.e. **4 hours before** `RQ4_SEED_RECOVERY.json` — which documents all
5 seeds (42-46) COMPLETE, `VERIFIED_CRYPTOGRAPHIC_PROVENANCE`, pre- and post-hoc leakage audits
both PASS, and a recomputed (not merely copied) `cosine_distance` mean of **0.9207** (95% CI
[0.8446, 0.9760]), independently matching the retrain worktree's own `aggregate_stats.json`
byte-for-byte. `RQ4_SEED_RECOVERY.json` even lists this exact file under its own
`external_references.master_close_verification` field — it cites the path but its `summary`/
`recommendation` do not incorporate what that file actually says. Read at face value (as a
recovery-audit artifact is meant to be read after a session restart), `RQ4_SEED_RECOVERY.json`
would lead a reader to conclude RQ4 evidence is missing and ~7 CPU-hours of retraining is
required, when in fact the branch's own tree already contains a verified, independently
recomputed COMPLETE_VALID result for exactly that work.

Root cause, as far as this session could establish: `RQ4_SEED_RECOVERY.json`'s own
`external_references` note says "Five-seed training evidence located on external worktree; not
accessible in current environment" — referring to `G:/gap010-rq4-retrain-20260924/`, which no
longer exists on this machine (`ls /g/gap010-rq4-retrain-20260924` → not found; this session
also confirmed `reports/production_readiness/20260924T000000Z_GAP010_RQ4_LEAKFREE_RETRAIN/`,
the exact directory name the task asked to cross-check against, does **not** exist in this
checkout or on current `G:` — it only ever existed inside that now-deleted external worktree).
So the underlying raw per-seed checkpoints are genuinely gone from this machine; only the
`RQ1_RQ4_MASTER_CLOSE` summary/verification JSON (which independently recomputed the
aggregate from the raw results before they vanished) survives as evidence, and it is
trustworthy on its own terms (it explicitly says it recomputed rather than copied, and matched
byte-for-byte).

**Compounding issue — this branch's own docs are stale on this exact point.** The commit that
was supposed to propagate the 0.9207 result into the human-readable docs, `a3843e3b` ("docs:
RQ4 now AUTHORITATIVE (leak-free retrain complete), close GAP-010 fully"), exists in the repo
(reachable from `integration/production-large-map-20260918` and several `docs/phase*-20260924`
branches) but **is not an ancestor of this branch's HEAD either** (same pattern as GAP-027).
Confirmed live: `README.md` on this branch still reads "RQ4 is **not currently citable as
authoritative** pending a leak-free retrain (GAP-010)" / "leak-free retrain not yet run
(`BLOCKED_EXTERNAL`)", and `docs/research/THESIS_TO_CURRENT_PROGRESS.md` (read in full for this
task) still cites only the superseded `cosine_distance=0.6434` figure and says "NOT CURRENTLY
CITABLE AS AUTHORITATIVE" — neither file mentions 0.9207 anywhere. So on this specific branch,
every doc a reader would normally trust (README, THESIS_TO_CURRENT_PROGRESS.md) *agrees* with
RQ4_SEED_RECOVERY.json's stale picture and disagrees with the actually-true, already-verified
0.9207 result sitting in this same branch's `reports/` tree. This is not a contradiction this
session can resolve by editing files (out of scope: verification only) — it is flagged here so
the coordinator knows this branch needs `a3843e3b` (or an equivalent doc sync) merged in before
any of its RQ4-related docs are trusted.

## Regression tests (task item 5)

Ran fresh in the isolated worktree (`G:/audit-worktrees/o20-verify-20260929`, real `pytest`,
not mocked):

```
pytest tests/unit/test_o15_rq1_five_run_matrix.py tests/unit/test_o16_rq3_pairing_preflight.py \
       tests/unit/test_o17_rq3_dataset_manifest_verifier.py tests/unit/test_o18_rq5_contract_audit.py -v
```

**Result: 14 passed, 0 failed.** All four modules' regression tests genuinely exist and
genuinely pass. But as detailed above, the O16/O17 test fixtures are narrow enough that they
never exercise the fail-open gaps found in this review (O16's tests never populate
`REQUIRED_SHARED` fields on the manual/automatic sides at all; O17's headline "valid manifest
passes" test is the exact case that exploits the `paired=None` fail-open default). Passing
tests here means the code does what its own narrow tests check, not that the code implements
the full contract described in the commit messages or this task.

## Summary table

| Item | Claim | Verified? | Key finding |
|---|---|---|---|
| O15 | 5 successful determinism runs | **NO** | Artifact says 0 runs, `INCOMPLETE`; fresh re-run this session reproduces 0/2 runs via a live GAP-027 crash not fixed on this branch |
| O16 | Full pairing-parity preflight | **PARTIAL** | Fail-open: manual/automatic-side field presence never enforced; core mismatch check untested/dead in practice |
| O17 | Dataset manifest pairing verification | **PARTIAL** | Fail-open: omitting `--paired` silently skips all cross-manifest checks and still reports PASS; tested as a legitimate pass case |
| O18 | RQ5(b) claim-boundary enforcement | **NOT ADDRESSED** | Audits an unrelated generic experiment-design-completeness question; no code anywhere on this branch enforces the unlabeled-vs-accuracy language rule |
| RQ4_SEED_RECOVERY.json | RQ4 seed-evidence state | **CONTRADICTS** already-verified 0.9207 result 4h earlier in same tree; branch's own README/THESIS_TO_CURRENT_PROGRESS.md are also stale on this point (missing commit `a3843e3b`) |

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
