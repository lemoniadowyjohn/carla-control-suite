# V133 integration dependency and ancestry ledger

Candidate branch: `integration/v132-pre-claude-source-candidate-20261119`
Candidate source HEAD before this evidence commit: `390a2c536c0ca5bb9131f43a4aa23265cf8272c2`
Production base: `225ed15d0da6444cc257835ca777aba281553f3c` (not modified).

| Line | Source head | Candidate commit | Ancestry/decision |
|---|---|---|---|
| Release #63/#70 + OC-A T3 | `7b655fb8db9f92682f41ad1e08404bd7c5ff657d` | `49d037696a21cba1ca5763d4dd25de86cc47c4b4` | Imported as stack; original five regressions repaired in OC-A; targeted acceptance/XML checks included in combined 445-pass run. |
| RL fuzzer #49 | `d30a0544e385e4b353f125a61cd678683d2c2a11` | `9010bc1b8c707c7ad7c28fa9a1f7be7d76f98523` | Production descendant; isolated source/tests; 5 focused tests pass and included in combined run. |
| Feature gap #56 | `af22f82c5095462b2bd2ae0f2a1c6b3bd09eba6` | `19b5be9862ce48013faee57c3c8d3e2d7633ded7` | Production descendant; missingness fail-closed behavior; combined run has one sklearn-dependent skip. |
| OSM #39/#57 | #39 `5368eda3448ef9a96588ad6ade8ac14a915bdd29`; #57 `694f1a419a184c5dea2de74f66d47a902014dc51` | `578f72786cb6a943cef43c2929c47e6448d1bd83` | Divergent. Six shared O1 implementation files have identical blobs. Selected #57 once as the O2 superset. Legal-movement helpers currently have no production callers; operational movement enforcement remains open. |
| Road graph #40 with #45/#46 | `5a360c600af940c78d82ca6e4a14e9f69c67ce07` | `390a2c536c0ca5bb9131f43a4aa23265cf8272c2` | #45 `e60c8182a47cabeb1790a1559435072ad5186909` and #46 `941212bc499bac62f266c7659d36b784f241539b` are ancestors of #40; merged after clean path-overlap check. 60 O3 tests pass. |
| RQ5 #52/#54/#55 + OC-D | OC-D `675a0fd2c54c705d57e85772c8d6bee0ec5d156a` | Excluded | Independent review REQUEST_CHANGES: malformed v2 split/pretraining evidence is accepted, producer omits split digest, and fresh-run enforcement is optional. #50 patch-id duplicates OC-D's change; neither imported. |
| Calibration #65/#66/#68/#69/T1 | T1 `00f059fbc067aace82212e2b768f016b0bd0d71b` | Excluded | Existing focused regression: `test_matching_camera_response_identity_validates_the_pair`; 141 passed, 1 failed. |
| CRS #67 | `66c1459d9a55a2482b7df740e628301ee8bdd726` | Excluded | Helper not yet wired into required production consumers; import alone would not close CRS defect. |
| Lifecycle/leases | #35/#60/#64; #37/#58 | Excluded | Exact-head Windows ownership/fencing tests and lineage review not completed. |

No GUI or GNN line was imported. The final evidence update is a documentation-only commit descended from the stated source HEAD. No production merge or CARLA execution occurred.
