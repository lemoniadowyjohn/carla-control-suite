# BC05 — Tests

All runs this session, `UP_DISABLE_CARLA=1`, `./.venv/Scripts/python.exe` (Python 3.12.2, pytest 9.0.1). Fresh evidence.

## Focused (lock + agent_sync)
```
tests/unit/test_agent_sync_contract.py ......   (6)
tests/unit/test_writer_lock.py .......... (10)
============================== 16 passed in 0.87s ==============================
```

## Full configured non-CARLA suite (`pytest.ini testpaths = ultimate_pipeline/tests tests/unit`)
```
====================== 329 passed, 48 warnings in 5.24s =======================
```
323 baseline (P0) + 6 new `test_agent_sync_contract.py` = 329, 0 failed / 0 errors.
Warnings are pre-existing `settings.py` optional-path `RuntimeWarning`s, not failures.

| Suite | Result |
|---|---|
| Focused lock + agent_sync | **16 passed** |
| Full configured offline | **329 passed, 0 failed** |
