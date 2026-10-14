# RQ2 local hull-footprint number — re-verification against current pin

Date: 2026-09-23

## Trigger

RQ2's authoritative local hull-footprint number (~2.7-3.8x) was originally computed
2026-08-21 through 08-26, before this session's 2026-09-14/16 bug fixes to
`GeoAligner.apply_to_xodr` (schema-order corruption), the alignment fallback extractor
(point-duplication), a stale-header-bbox bug, and `CurvatureGap`'s KL-divergence
density-vs-probability-mass bug. `docs/research/STALE_ARTIFACT_POINTERS.md` and
`docs/research/THESIS_TO_CURRENT_PROGRESS.md` both flagged that the "human call, not an
automatic swap" of re-verifying this number against post-fix code/current pin had not
been made as of the time those files were written. This task makes that call, with a
fresh, independent re-run.

**Pre-existing complication found during this task**: `docs/research/THESIS_TO_CURRENT_PROGRESS.md`
already records a 2026-09-17 re-verification pass (commit `c3915130`) that re-ran this exact
script against the pin current at that time. That pin (`370abbbbb3...`) turns out to still be
the current pin today (2026-09-23) — no promotion has landed since. So this task's re-run is a
second, independent re-verification of the same pin/code combination the 09-17 pass already
covered, not a verification against a *new* pin. See "Verdict" below for what that means.

## Exact commands run

Worktree: `G:/carla-rq2-reverify-20260923`, checked out from
`origin/integration/production-large-map-20260918` at commit `a5a2a5da9a4429ac0ebfed2100a9f9f2db4b2418`
(2026-09-22 22:23:57 +0200 — the current tip of that branch), on new branch
`docs/rq2-reverification-20260923`.

```
UP_DISABLE_CARLA=1 python scripts/regen_local_registration.py
UP_DISABLE_CARLA=1 python scripts/regen_frechet_distance.py
```

(`python` = `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\.venv\Scripts\python.exe`,
Python 3.12.2, run from inside the worktree — the worktree has no venv of its own so the shared
repo venv was pointed at it.)

`scripts/regen_local_registration.py` is the real RQ2 hull-footprint entrypoint (the repo's own
C14/C26 lineage — `ultimate_pipeline/domain_gap/local_registration.py`, called via
`compute_local_registration(auto_xodr, manual_xodr, footprint="hull"|"bbox")`). It resolves the
auto-side XODR through `ultimate_pipeline.carla_tools.map_registry.verify_pinned_map("auto_map_of_record")`
— no hardcoded path — so it always measures against whatever is actually pinned.
`scripts/regen_frechet_distance.py` is the sibling entrypoint for the related local Fréchet-distance
number (thesis future-work item #14), calling `ultimate_pipeline.domain_gap.frechet_gap.compute_frechet_gap`
directly.

## Exact inputs

Confirmed live via `verify_pinned_map("auto_map_of_record")` inside the worktree, and independently
re-hashed with `sha256sum` (not just trusting the script's self-reported hash):

| Role | Path | SHA256 |
|---|---|---|
| Auto (map-of-record) | `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr` | `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8` |
| Manual (reference) | `campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr` | `5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c` |

Both hashes match `docs/runtime/MAP_OF_RECORD.md` exactly. No newer map-of-record promotion exists:
the last commit touching `ultimate_pipeline/carla_tools/map_registry.py` is `25722002` (2026-09-17,
a docs-only correction, not a re-pin), and no `feat(map): promote ...` commit appears after it on
`integration/production-large-map-20260918` through its current tip `a5a2a5da` (2026-09-22).

## Result: unchanged, byte-identical to the 2026-09-17 re-verification

The freshly regenerated `local_registration.json` and `frechet_distance.json` are **byte-for-byte
identical** to the versions already committed in the repo at
`reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/` (`diff` shows zero differences). Full outputs
are archived alongside this report as `local_registration.json` and `frechet_distance.json`.

**Hull footprint (primary/default) — RQ2 headline numbers:**

| Metric | Original (08-21/08-26, pre-fix, stale pin) | 2026-09-17 re-verify (post-fix code, pin `370abbbbb3`) | 2026-09-23 re-verify (this task, same pin, current tip) |
|---|---|---|---|
| Road-length ratio (auto/manual) | 2.69x | **2.683x** | **2.683x** |
| Junction ratio (auto/manual) | 3.78x | **3.782x** | **3.782x** |
| Road-count ratio (auto/manual) | 3.57x | **3.561x** | **3.561x** |
| Curvature gap | 0.2192 | 0.2206 | 0.2206 |
| Lane-width gap | 0.0415 | 0.0597 | 0.0597 |
| Building density gap (in-footprint) | — | 0.2308 (3,279/5,682 kept vs. 993 manual) | 0.2308 (3,279/5,682 kept vs. 993 manual) |

**Local Fréchet distance (thesis item #14, related curvature/completeness metric):**

| Metric | Pre-09-17 (stale pin `744757f3`) | 2026-09-17 / 2026-09-23 (pin `370abbbbb3`) |
|---|---|---|
| Mean | 55.28 m | **58.18 m** |
| Median | 35.26 m | **36.13 m** |
| p90 | 128.01 m | **140.48 m** |
| Matched pairs | 895 | 894 |

## Verdict

**The ~2.7-3.8x hull-footprint figure holds, exactly reproduced, no material change.**

Two independent facts explain why re-running today produced the identical result to 09-17 rather
than something new:

1. **The current pin has not moved since 2026-09-17.** The map-of-record used for both the 09-17
   re-verification and this one is the same file (`370abbbbb3...`, promoted `3ac77b37`,
   2026-09-16/17). No later promotion exists on this branch as of its 2026-09-22 tip. Re-running the
   same script against the same inputs with the same code correctly reproduces the same number —
   this is a successful reproducibility check, not new evidence of stability under a new pin.

2. **The 2026-09-14/16 GeoAligner / point-duplication / stale-header-bbox / CurvatureGap-KL fixes
   this task was framed around do not touch this code path at all.** Verified independently by
   grepping `ultimate_pipeline/domain_gap/local_registration.py` and
   `ultimate_pipeline/domain_gap/frechet_gap.py` for imports of `GeoAligner` or `CurvatureGap`: zero
   matches in either file. Both modules are self-contained (their own convex-hull crop, their own
   curvature-gap calculation, their own coordinate-frame handling) and never call the fixed modules.
   `docs/research/THESIS_TO_CURRENT_PROGRESS.md`'s 2026-09-17 entry already stated this caveat
   explicitly, and this task's independent code inspection confirms it. **There was never a
   mechanism by which those four specific fixes could have moved this number** — the premise that
   they might have is false for this metric, though it was a reasonable thing to check rather than
   assume.

What *did* legitimately change the underlying map between the original 08-21/08-26 baseline and
today is five map-of-record promotions (09-02, 09-04 x2, 09-05 x2, 09-17), including two real
pipeline bug fixes (`946228f9` — hardener no longer strips road-level `<link>` from junction
connectors; `a13efd91` — `GeometryValidator` repairs degenerate `<planView>` instead of leaving it
empty). Despite those real map changes, the hull-footprint ratios moved by less than 0.5% (2.69→2.683,
3.78→3.782, 3.57→3.561) — this is itself informative: it says the RQ2 completeness-gap finding is
robust to several rounds of real pipeline hardening, not an artifact of one specific buggy map
snapshot. The curvature_gap (0.2192→0.2206) and lane_width_gap (0.0415→0.0597, the largest relative
move, still small in absolute terms) shifts were already present in the 09-17 pass and are unchanged
today.

**No documentation update is needed.** `docs/research/THESIS_TO_CURRENT_PROGRESS.md`'s RQ2 row and
its 2026-09-17 note already state the exact current figures (2.683x/3.782x/3.561x hull;
58.18m/36.13m/140.48m Fréchet) accurately — this task's independent re-run confirms them rather than
superseding them. The ~2.7-3.8x range statement in the RQ2 table header remains accurate (2.683x and
3.782x both fall inside that stated range). No file/line requires a flagged edit.

**This does not change anything for the thesis.** The finding is a successful reproducibility
confirmation: same pin (still current), same code path (unaffected by the unrelated fixes), same
result, independently re-derived and re-hashed rather than trusted from the prior report.

## Caveat carried forward

Same caveat as the 09-17 pass, re-confirmed by this task's own import-grep rather than taken on
faith: the RQ2 hull-footprint and local-Fréchet numbers are stable under the regenerated **map**
(the `xodr_carla_hardener`/`GeometryValidator` fixes), but say nothing about the `GeoAligner`/
`CurvatureGap` **code** fixes, because `local_registration.py` and `frechet_gap.py` never exercise
that code. If those specific fixes are ever expected to move the RQ2 local number, that would
require porting/reusing them inside `local_registration.py` — a methodology change, not a re-run,
and out of scope here.

## Full-suite test run

No source code was modified as part of this task (only new report files were added: this
directory plus the regenerated JSON already tracked in
`reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/`, which came back byte-identical to what
was already committed). Per this repo's convention, a full bare `pytest` is still run before
commit; see the branch's CI/local run for the pass/fail count at commit time.
