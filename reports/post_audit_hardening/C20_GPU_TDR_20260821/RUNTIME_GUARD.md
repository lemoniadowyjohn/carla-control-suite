# C20 GPU TDR Runtime Guard

Date: 2026-08-21

Verdict: GPU_TDR_RUNTIME_GUARD_ADDED

## Problem

The C20 Event Viewer audit found chronic Windows `LiveKernelEvent 141` GPU/display watchdog failures on this machine. That is an environmental fault: CARLA runtime evidence collected while those events are still firing is not trustworthy.

The earlier VRAM/thermal explanation was explicitly falsified by the `-nullrhi` control. The actionable blocker is the TDR stream, not a proven map or pipeline defect.

## Guardrail Added

`ultimate_pipeline.core.gpu_tdr_preflight` now queries recent Windows Error Reporting events for:

- provider: `Windows Error Reporting`
- event text: `LiveKernelEvent`
- code: `141`

CARLA lifecycle code calls the preflight before:

- launching/restarting CARLA;
- connecting to an already-running CARLA server through `autostart_carla_if_needed`.

If recent `LiveKernelEvent 141` records are found, CARLA launch/connect fails closed with a clear message pointing to this C20 evidence folder. Offline tests skip the check when `UP_DISABLE_CARLA=1`.

## Operator Recovery Runbook

This code cannot repair the GPU driver or hardware. The required hands-on sequence is:

1. Stop CARLA and other GPU-heavy processes.
2. Confirm the idle machine stops producing new `LiveKernelEvent 141` records.
3. If events continue, clean-reinstall the NVIDIA Quadro driver:
   - boot Safe Mode;
   - remove the current display driver with DDU;
   - install a known-stable Quadro driver branch older than `573.22`;
   - reboot normally.
4. Re-check Event Viewer at idle. Do not run CARLA until the 141 stream stops.
5. Run a short GPU health/stress check while monitoring temperature and new watchdog events.
6. If `LiveKernelEvent 141` persists after clean driver rollback, treat the GPU/machine as unsuitable for thesis runtime evidence and move CARLA capture to different hardware.
7. Only after the preflight passes, rerun the CARLA patient probe and live-drive/load gates.

## Tests

Unit tests mock the Windows event-log query and assert:

- non-Windows hosts skip safely;
- no recent events passes;
- recent `LiveKernelEvent 141` blocks;
- event-log query failure fails closed;
- `UP_DISABLE_CARLA=1` skips for offline tests;
- `restart_carla` does not call `Popen` when the TDR preflight fails.

Full-suite status must be recorded by the landing commit.

Targeted offline tests:

```text
22 passed, 3 warnings
```

Full offline suite:

```text
1041 passed, 97 warnings in 249.90s (0:04:09)
```
