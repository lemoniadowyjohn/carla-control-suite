# Review matrix

| Review subject | State | Evidence / owner |
|---|---|---|
| Candidate source integration | REQUEST_CHANGES | Independent reviewer checked exact `c95f9b4ece19b98fad2a1818f658fbe8686f0faa`; P0 fixed, scientific source blockers remain |
| #69 calibration and capture contract | Source integrated; physical acceptance pending | Unit/mock tests only; no live CARLA |
| #65 native intrinsics | Offline verified in focused suite | Final rendered-frame compliance not verified |
| #50/#55 RQ5 identity | Offline guards passed; training suite partial | `torchvision` absent; no actual training/evaluation |
| #67 CRS | Offline API tests pass | No live map route equivalence claim |
| #64 lifecycle | 106 focused tests pass | No Windows CARLA process/server qualification |
| #30 release review threads | Pending adjudication | 19 threads inventoried; 18 currently unresolved and 1 resolved (comment 4543969708). Candidate has no PR30/#63 fix; adjudication remains open. |
| #37/#58 lease | Excluded | Two known unresolved recovery threads; WSL/NTFS durability unverified |

## Independent review findings

Reviewer verdict on prior candidate SHA `1c392707f3c7b6b6742e7fba204fac5d429e6c2f`: REQUEST_CHANGES. P0 shared cache purge was removed in `7b0194caf6dfac4bbcbc63e0ab5b9397b95ae1f2`; two EOF whitespace findings were fixed in `8d7e5912f981253826e1fb87d78422bf135621e7`. Remaining P1/P2 findings are RQ5 split manifest generation, production-wired RQ3 expected counts, CRS route adoption, and camera remap receipt wiring. Fresh review of the final commit remains pending.


Final exact-SHA reviewer recheck: `c95f9b4ece19b98fad2a1818f658fbe8686f0faa`. Verdict remains REQUEST_CHANGES for release because RQ5 split proof, RQ3 expected-count wiring, CRS adoption and applied-intrinsics wiring are incomplete. Reviewer confirmed P0 purge removal and clean base-to-head diff.
