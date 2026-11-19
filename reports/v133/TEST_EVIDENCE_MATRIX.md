# V133 focused test evidence

Environment: Windows, Python 3.12.2, pytest 8.0.1, candidate worktree. Candidate source SHA under test: `390a2c536c0ca5bb9131f43a4aa23265cf8272c2`.

| Suite | Result | Limitations |
|---|---:|---|
| Combined OC-A/release XML + #49/#56/#57/#40 regressions | 445 passed, 1 skipped, 0 failed; exit 0 | `tests/unit/test_feature_gap.py::...` skipped because `sklearn` is unavailable. Command is recorded verbatim in `reports/v132/v132_source_candidate.json`. |
| PR #40 O3 road graph/orphan focused modules | 60 passed, 0 skipped/failed; exit 0 | CARLA-independent tests only. |
| `git diff --check` | exit 0 after merge whitespace cleanup | Applied to candidate changes. |
| `compileall` | exit 0 | `python -m compileall -q` on the three O3 implementation modules, `ultimate_pipeline/experiments/rl_fuzzer.py`, and `ultimate_pipeline/domain_gap/feature_gap.py`. |
| Full offline CI / exact-head GitHub Actions | NOT_RUN | No exact candidate run evidence. |
| CARLA runtime / paired RQ3 / RQ5 training | NOT_RUN | No live server, admitted data, or experiment execution claimed. |

Raw pytest stdout was observed in the tool session but not persisted as a log; no log digest is asserted. A full dependency-complete suite remains outstanding.
