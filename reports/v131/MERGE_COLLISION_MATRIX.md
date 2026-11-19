# Merge collision matrix

| Area | Inputs | Resolution | Verification / limitation |
|---|---|---|---|
| Sensor rig, calibration, intrinsics | #65 and #69 | #69 contract retained; #65 native K functionality reconciled once | Applied-rig/calibration and intrinsic tests pass; physical mounts and live rendered K remain unverified |
| Route capture / safe runner | #64 over #69 | Manually retained #69 calibration-v2 checks and receipt binding while applying #64 ownership-only process lifecycle | 106 lifecycle/rig tests passed on integrated implementation; CARLA not run |
| RQ5 provenance and runner | #50 with #55 | Kept separate provenance module and runner checks; avoided duplicate guards | #50 six tests and #55 thirteen tests passed; broader trainer tests blocked by torchvision |
| CRS | #67 | Retained explicit distinction between auto native tmerc+offset and manual EPSG:32632 | Local registration tests pass; route executor not wired |
| submission mirrors | T2 + #69 | Canonical route recorder mirror synchronized; retained applied-rig module mirror required by isolated import test; reverted unrelated mirror edits | mirror test passed |
| XML/release authority | #30/#63/#70 | Not imported | #70 tests fail; #63 awaiting OC-A and independent review; PR #30 review debt unresolved |
| leases | #37/#58 | Not imported | recovery review threads unresolved; WSL/NTFS durability not tested |

No global ours/theirs conflict strategy was used. The report commit is separate from source merges.