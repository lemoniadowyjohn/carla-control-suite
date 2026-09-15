# Grid0821/0828 Root Cause Assessment

**Date:** 2026-09-15
**Harness:** grid_runtime_harness.py (offline, runtime BLOCKED)

## Ranked Hypotheses (by observed evidence)

1. **ASensor::EndPlay teardown (native crash)** — Rank 1
   - Evidence: Grid0821 semantic camera, 120 frames, RPC disconnect, exit -11, UE log `ASensor::EndPlay`, not in Town10HD
   - Mitigation: `UP_SKIP_DESTROY` bypasses destroy, mitigates but does not eliminate root cause

2. **Streaming pool exhaustion** — Rank 2
   - Evidence: Grid0828 LiDAR+RGB, queue overflow, streaming disconnect, no server crash
   - Mitigation: `UP_SKIP_STREAM_CHECK` bypasses detection, does not eliminate pool use

## UP_SKIP Assessment

- `UP_SKIP_DESTROY`: **Mitigates** teardown crash, **bypasses detection** for destroy order, does not eliminate native crash
- `UP_SKIP_STREAM_CHECK`: **Bypasses detection** for streaming disconnect, does not eliminate pool exhaustion

## Status

BLOCKED — harness fully implemented offline and tested with mock CARLA; runtime execution BLOCKED (CARLA 0.9.16 server not available on this host). Re-run on host with CARLA to confirm.

## Next

Run harness on CARLA host with Town10HD/Grid0821/Grid0828 matrix, 3 repetitions, record RAM/VRAM/draw calls/triangles/streaming pool.
