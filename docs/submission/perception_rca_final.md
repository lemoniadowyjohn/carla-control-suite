# Perception RCA Final

Date: 2026-04-30

## Status

RQ3 remains deferred. This note documents why the manual Grid0828 capture could not be converted into paired perceptual-domain-gap evidence and what diagnostic tool is now available.

## Historical Failure Evidence

| Artifact | Observed value | Interpretation |
|---|---:|---|
| `carla_status.json` | `failure_reason=EMPTY_RECORDER_MANIFEST` | CARLA RPC/map probe succeeded, but no evidence pack was produced. |
| `carla_status.json` | RPC `2000` reachable, streaming `2001` reachable | The recorded failure is not explained by the outer port contract alone. |
| `recording_summary.json` | `frames_recorded=0`, `frames_requested=400` | No usable RGB evidence was captured for Grid0828. |
| `recording/recorder_manifest.json` | `total_files=0`, `sensors=[]` | The recorder had no registered sensor outputs. |
| `recording/sensor_rig_report.json` | `rig_attach_attempted=true`, `listener_callbacks_registered=0` | The failure occurs at rig attach/listener-registration or immediately before callback delivery. |
| `recording/tick_watchdog.json` | `advanced=true`, `n_ticks=5` | The world ticked; the failure is not simply a frozen world loop. |

The historical `carla_world_settings` fields record `synchronous_mode=false` and `fixed_delta_seconds=0.0` before the recorder phase. They do not record `no_rendering_mode`, so the old artifact cannot prove whether no-render mode was active.

## Current Code Boundary

The current `record_route_fixed.py` applies synchronous mode before `SensorRecorder.attach(...)` and asserts that sync is enabled before listener registration. This addresses the earlier ordering risk. The remaining failure mode is therefore likely CARLA-runtime specific: listener registration, native sensor streaming, or custom-map rendering/streaming behavior on Grid0828.

## Added Diagnostic

New standalone tool:

```powershell
python ultimate_pipeline/tools/diagnose_perception_blockers.py --host 127.0.0.1 --port 2000 --map-name Grid0828 --out-dir artifacts/perception_diagnostics/
```

The script checks:

| Check | Purpose |
|---|---|
| CARLA Python API import | Detects missing `carla` module and reports the expected 0.9.16 egg path. |
| RPC server | Confirms port 2000 and server version. |
| Streaming port | Probes port 2001. |
| Map load | Attempts to load `Grid0828`. |
| `no_rendering_mode` | Fails early if sensor callbacks would be disabled. |
| Spawn points | Confirms a valid ego spawn source. |
| Single RGB callback | Spawns one ego vehicle and one RGB camera, ticks 20 times, and requires at least 5 callback frames. |

## Remaining Blockers

| Blocker | Fixability before defense | Notes |
|---|---|---|
| Grid0828 zero-frame capture | Diagnostic only | Requires a live CARLA session; not safe to treat as thesis evidence until the diagnostic passes. |
| Full generated-map semseg | Not pipeline-fixable | Standalone OpenDRIVE worlds lack UE4 semantic material tags; a UE4 cook is required. |
| Paired manual-vs-generated perception | Deferred | Requires stable Grid0828/manual capture and generated-map capture on aligned extents. |

## Defense-Safe RQ3 Wording

Sensor-rig mechanics and limited RGB delivery are demonstrated as bounded evidence only. The thesis does not claim a completed paired perceptual domain-gap measurement, generated-map semantic segmentation validity, or sim-to-real model generalization.
