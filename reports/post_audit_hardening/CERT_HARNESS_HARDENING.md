# Cert Harness Hardening

## Result

- Verdict: `HARNESS_HARDENED_GREEN`
- Code commit: `64c427d7`
- Baseline pytest: `639 green` from the provided offline suite baseline
- Final pytest: `645 passed, 0 failed`
- Test command: `UP_DISABLE_CARLA=1 .\.venv\Scripts\python.exe -m pytest -q --tb=short`

## What Changed

- Added a tracked cert-runtime package under `ultimate_pipeline/tools/cert_runtime/`.
- Moved the P4 evidence producers into governed, importable modules.
- Kept root compatibility shims at `/_run_p4_equiv.py` and `/_write_p4_evidence.py`.
- Added a shared resolver for candidate and evidence directories.
- Added a fail-closed `assert_candidate_consistency(...)` preflight.
- Refactored `phase_l_validation.py` and `run_n_certify.py` to consume the shared resolver.
- Added offline synthetic unit tests for resolver behavior, digest preflight, and the promoted producers.

## Files Added

- [\_run_p4_equiv.py](/C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/_run_p4_equiv.py)
- [\_write_p4_evidence.py](/C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/_write_p4_evidence.py)
- [tests/unit/test_cert_runtime_hardening.py](/C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/tests/unit/test_cert_runtime_hardening.py)
- [ultimate_pipeline/tools/cert_runtime/__init__.py](/C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/ultimate_pipeline/tools/cert_runtime/__init__.py)
- [ultimate_pipeline/tools/cert_runtime/runtime_config.py](/C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/ultimate_pipeline/tools/cert_runtime/runtime_config.py)
- [ultimate_pipeline/tools/cert_runtime/run_p4_equiv.py](/C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/ultimate_pipeline/tools/cert_runtime/run_p4_equiv.py)
- [ultimate_pipeline/tools/cert_runtime/write_p4_evidence.py](/C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/ultimate_pipeline/tools/cert_runtime/write_p4_evidence.py)

## Files Updated

- [phase_l_validation.py](/C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/phase_l_validation.py)
- [run_n_certify.py](/C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/run_n_certify.py)

## Notes

- The gate logic was not changed.
- No CARLA runtime was used in tests.
- No `.xodr` or campaign artifacts were mutated.
- `ESCALATE_TO_CLAUDE`: not needed for this offline harness hardening pass.

