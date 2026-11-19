# V131 candidate closure status

- SOURCE_IMPLEMENTED: YES for the listed integrated source stacks; T1 applied-rig fix is PARTIAL, not complete.
- MERGED_IN_CANDIDATE: YES, local nonproduction candidate only. No production merge.
- FULL_OFFLINE_CI: BLOCKED_ENVIRONMENT (21 collection errors on baseline-style full pytest; focused combined: 388 pass / 17 fail / 1 skip).
- INDEPENDENT_SOURCE_REVIEW: PENDING.
- CARLA_RUNTIME: NOT_RUN.
- RQ3_DATASET: NOT_ADMITTED / NOT_RUN.
- RQ5_MODEL_VALIDATION: NOT_RUN.
- PRODUCTION_GO: NO.

Candidate readiness is reviewable source integration, not release readiness. The 17 failures are due to missing torchvision imports; no baseline comparison has established them as newly introduced. Sparse checkout also omits map assets used by three PR67 adjacent tests.

## Follow-up safety correction

The independent review's P0 shared-directory deletion finding was fixed in `ultimate_pipeline/carla_tools/carla_recovery.py` commit `7b0194caf6dfac4bbcbc63e0ab5b9397b95ae1f2`; both restart entrypoints now avoid cache/temp deletion. Targeted regression: 51 passed, 0 failed, 0 skipped. Exact source diff whitespace check was corrected in `8d7e5912f981253826e1fb87d78422bf135621e7`. Independent review of the resulting final SHA remains pending. RQ5 split proof, RQ3 planned-count wiring, CRS caller adoption and effective-K receipt wiring remain blockers.


The RQ3 cross-arm suite is not green: 113 collected, 102 passed, 11 failed; ten substantive failures remain due to omitted pinned map assets and an outdated/synthetic incomplete rig fixture. One timing failure passed isolation. Full offline CI is still blocked.
