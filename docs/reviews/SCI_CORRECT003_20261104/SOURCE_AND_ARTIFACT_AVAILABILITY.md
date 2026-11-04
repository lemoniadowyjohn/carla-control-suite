# Source and artifact availability (2026-11-04)

| Artifact | GitHub | Local | Note |
|---|---|---|---|
| Integration code `1a36b560` | yes | yes | |
| GAP-070 candidate `2cee039f` | yes | yes | |
| Run code `22cf39ab` (producer of run 20261007) | yes (object present) | yes | used for the R-13 trace |
| C1 work in progress | no | yes (uncommitted, `E:/wt/fix-gap070-connector-snap-safety-c1-20261104`) | not reviewable for acceptance |
| O13 validator | no | no | NOT_RUN |
| X9 inventory `06a31ed1` | **no** (local branch) | yes | |
| Run 20261007 stage files (8; 1,063,561,918 bytes) | no | yes | archive proposal in the C0 package |
| Run 20261007 manifest and receipts (`run_manifest.json`, `settings_snapshot.json`, `stage6_containment_runtime.json`, `sumo_netconvert.log`) | no | yes | small; can be archived together with the stage files |
| Map-of-record `370abbbb…` | yes (LFS, registry pin) | yes | |
| Grid0828 `5eaece23…` | yes (registry) | yes | |
| Grid0821, candidate_connectivity_repaired | no (gitignored or local) | partly; prefix hashes only | RQ4 identity incomplete |
| RQ4 checkpoints (5) | no | G: (md5) | |
| RQ4 562 tiles | no | location unknown | |
| RQ1 Osm2Odr outputs (3) | no (gitignored) | not verified | |
| Review packages ARCH-X8-X9, ARCH-002, ARCH-003, SCI-ARCH-001, this one | no | yes (`reviews/`) | C0 staging exists for the first two only |

**Missing dependencies for reproduction:**
- Python 3.12 + shapely 2.x and the repository sources;
- about 3 GB of RAM per map parse;
- none beyond the inputs above.
