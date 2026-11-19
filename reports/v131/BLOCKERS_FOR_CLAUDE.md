# Bounded independent review request

Review the final pushed candidate head recorded in `CANDIDATE_SHA.txt`; the first independent review was on `1c392707f3c7b6b6742e7fba204fac5d429e6c2f` and returned REQUEST_CHANGES. Focus on semantic conflict resolutions in sensor calibration/intrinsics, RQ3 fail-closed behavior, CRS frame distinctions, RQ5 identity binding and lifecycle process ownership. Independently reproduce negative controls; do not certify live CARLA or science from fixtures.

Already corrected in follow-up: the P0 shared cache/temp purge in `carla_recovery.py` was disabled and 51 lifecycle/ownership tests passed; two whole-range diff whitespace findings were fixed. Remaining blockers: 17 focused RQ5 tests cannot import because torchvision is absent; full suite collection is blocked by optional dependencies and omitted full-map assets; PR #30 has 19 threads: 18 unresolved and one resolved; none were resolved by this work, and candidate source fixes are not integrated; #37/#58 recovery review and WSL/NTFS test remain pending; #70 is excluded with CI failures; #63 is excluded pending OC-A and independent review; CARLA runtime, RQ3 paired dataset and RQ5 training/evaluation were not run.


## Reproduced RQ3 cross-arm gap

On source `8d7e5912f981253826e1fb87d78422bf135621e7`, the recorded cross-arm suite collected 113: 102 passed, 11 failed. Ten failures are reproducible blockers (9 missing pinned Ingolstadt XODR and 1 synthetic applied-rig fixture rejected by the trusted full-set contract); one stale-callback timeout was transient and passed when isolated. See the raw log and `TEST_MATRIX.json`.


## Independent review outcome

The independent reviewer rechecked exact commit `c95f9b4ece19b98fad2a1818f658fbe8686f0faa`: P0 purge issue and whitespace findings are fixed. Review disposition is REQUEST_CHANGES until the four source blockers above are addressed.
