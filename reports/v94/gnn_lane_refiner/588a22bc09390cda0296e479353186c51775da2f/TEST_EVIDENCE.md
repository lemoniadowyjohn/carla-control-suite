# V94 verifiable test evidence

Source commit: `588a22bc09390cda0296e479353186c51775da2f`. Base commit: `225ed15d0da6444cc257835ca777aba281553f3c`. Remote source blob: `43745b5c9f9b2601f72c986a3d47cdc737b315e3`. Remote test blob: `9d9e6b8d95cb50ba00a7ca2ed619e3c248d7e102`. These are identical to Git blobs from the locally exercised source and test files.

Environment: Linux 6.18.57 x86_64, Python 3.13.5, pytest 9.0.2, isolated minimal overlay holding the exact committed refiner/test files. This is NOT a full checkout. Direct `git ls-remote` / clone was unavailable (GitHub DNS resolution failed); production Windows worktrees were not present.

| Check | Exact command / procedure | Exit | Result |
| --- | --- | --- | --- |
| Old control | `python behavioral_control.py ../v94_gnn_baseline/ultimate_pipeline/ml/lane_gnn_refiner.py` | 1 | Intended FAIL: old stub silently returned None |
| Fixed control | `python behavioral_control.py ultimate_pipeline/ml/lane_gnn_refiner.py` | 0 | PASS: configured model rejected without mutation |
| Targeted | `cd /mnt/data/v94_gnn_worktree && PYTHONPATH=. python -m pytest -q tests/unit/test_lane_gnn_refiner_fail_closed_v94.py` | 0 | 26 passed, 0 failed, 0 skipped, 0 collection errors |
| Syntax | `python -m compileall -q ultimate_pipeline/ml tests/unit/test_lane_gnn_refiner_fail_closed_v94.py` | 0 | PASS |
| Ruff | `ruff` not installed | NOT_RUN | BLOCKED_ENV |
| Full repository suite | Repository checkout unavailable | NOT_RUN | BLOCKED_EXTERNAL |
| Windows | Not accessible | NOT_RUN | BLOCKED_EXTERNAL |
| Training / held-out genuine maps / CARLA | No validated correction data, checkpoint or authorized runtime | NOT_RUN | BLOCKED_DATA / BLOCKED_EXTERNAL |
| CI on exact implementation/evidence SHA | Not verified at evidence creation | NOT_RUN | PENDING |

SHA-256 source file: `017a4eda1517f7196709ce06f865e338470c781b19def4974c3f55379b44528d`; test file `71747e0dc228aedfa37780f590b539bd5516ddea8d5b7af4b845225003036e2c`. Log hashes: `pytest.log` `7b2495bd93e2ebabc31e0f4b2c9a4df34834ce9f75c31a3e0bf7d8e527a0faf0`; `baseline_control.log` `e41dc3eb809117d2ad5ba45773c2b3475a1c8dbbd83269408324239255fe69c5`; `fixed_control.log` `1ae258c5a7d7789533b19ad8e0672636cb052f96312f105094cca237e5655e61`. `behavioral_control.py` `1bd9149da3a8fb9cd4183d1b9accfe3d471c5302a5166bce44769bd39a025fe1`.

The original source's Git blob SHA `1e25cffc053c405ca1ee810edb41a0e02b08d374` was matched exactly. Passing only the isolated test suite does not establish release readiness.
