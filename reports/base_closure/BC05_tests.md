# BC05 — Tests

All runs this session, `UP_DISABLE_CARLA=1`, `./.venv/Scripts/python.exe` (Python 3.12.2, pytest 9.0.1). Fresh evidence.

## Focused (lock + agent_sync)
```
tests/unit/test_agent_sync_contract.py ......   (6)
tests/unit/test_writer_lock.py .............. (14)
============================== 20 passed in 1.15s ==============================
```

## Full configured non-CARLA suite (`pytest.ini testpaths = ultimate_pipeline/tests tests/unit`)
```
====================== 333 passed, 48 warnings in 5.41s =======================
```
323 baseline (P0) + 10 new lock-governance tests = 333, 0 failed / 0 errors.
Warnings are pre-existing `settings.py` optional-path `RuntimeWarning`s, not failures.

| Suite | Result |
|---|---|
| Focused lock + agent_sync | **20 passed** |
| Full configured offline | **333 passed, 0 failed** |
