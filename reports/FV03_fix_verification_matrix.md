# FV03 Fix Verification Matrix

Generated: 2026-07-29T22:08:06.986665+00:00

Repository: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main`
Branch: `verification/map-quality-hardening-20260729`
Reviewed source SHA: `6d11a973202ed9039e21b4d93e914bce0632ec18`

| issue_id | subsystem | status | focused_test_result | full_suite_result | remaining_weakness | repair_commit |
| --- | --- | --- | --- | --- | --- | --- |
| GEO-LINE-ARC-AUTH | geometry | FIXED_VERIFIED | 89 passed; scaffold 2202 passed/78 skipped | 305 passed/48 warnings | Poly3/Spiral still unsupported by canonical evaluator | 6d11a973 |
| MAP-PLOTTER-ZERO-K | visualization | FIXED_VERIFIED | scaffold passed | 305 passed | none for Line/Arc path | pre-existing before 6d11a973; reverified |
| MAP-DIFF-CURVATURE | visualization | FIXED_VERIFIED | scaffold passed | 305 passed | none for Line/Arc path | pre-existing before 6d11a973; reverified |
| STAGE6-STRAIGHT-CHORD | stage5/stage6 | FIXED_VERIFIED | 28 passed for junction/stage6 containment slice | 305 passed | connector rebuild remains opt-in structural mutator; artifact transaction precondition not satisfied | 6d11a973 |
| CONTRACT-COLLECTION | test infrastructure | FIXED_VERIFIED | 305 collected | 305 passed | large parent maps not committed; strict fixture provenance requires external archive | 6d11a973 |
| ARTIFACT-TX-INCOMPLETE | artifact safety | OPEN_CONFIRMED | import ultimate_pipeline.artifacts failed: missing promotion.py | not collected | do not authorize structural map mutation until completed/tested | none |
| CARLA-RUNTIME | CARLA/perception | BLOCKED_RUNTIME | 10 local carla_tools tests passed | not in pytest.ini; local unconfigured 30 passed | no claim of drivability or perception certification | 6d11a973 for contract helpers only |
