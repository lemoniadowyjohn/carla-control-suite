# C20 Tier 1 probe results — the RPC hang is NOT render/VRAM-bound

Ran the Tier 1 sequence from `C20_CARLA_RUNTIME_UNBLOCK.md` using `scripts/c20_tier1_probe.py`, which
polls `client.get_server_version()` directly (the actual gap: `ultimate_pipeline.core.carla_utils.restart_carla`
only waits for the TCP port to open, never confirms RPC responds — that's why past "restarted
successfully" reports were misleading).

## Results

| attempt | flags | timeout | outcome | GPU behavior |
|---|---|---|---|---|
| patient (cold) | `-RenderOffScreen -quality-level=Low -nosound` | 600s | TIMEOUT | VRAM→5923/6144 MiB by 30s, stays pegged; temp→82°C by 94s, stays; util oscillates 65-96% continuously |
| patient (warm, same DDC cache) | same | 180s | TIMEOUT | same pattern — disproves "slow shader compile" |
| **`-nullrhi`** | `-nullrhi -nosound` | 90s | TIMEOUT | **VRAM stays 0 MiB the entire time; temp actually drops (71→67°C); util ~0%** |
| `-nullrhi` (longer) | same | 300s | TIMEOUT | same — VRAM never leaves 0 MiB |

## Direct process check (outside the probe script)

Launched CARLA with `-nullrhi` directly and sampled the `CarlaUE4-Win64-Shipping.exe` process:
- **CPU time: 53.5s → 66.6s over 10 wall-clock seconds** (actively consuming >1 CPU-core-equivalent
  across its 59 threads) — not idle, not blocked-waiting.
- **Working-set memory: flat at ~5.91 GB** the entire time — not growing, so not making forward
  progress loading assets either.
- No entries appeared in `%LOCALAPPDATA%/CarlaUE4/Saved/Logs` or `Saved/Crashes` across any attempt —
  whatever it's stuck on happens before UE's own logging subsystem flushes anything.

## Conclusion — C20's core hypothesis is falsified

`-nullrhi` disables the rendering hardware interface entirely — CARLA never touched the GPU (VRAM
stayed at 0 MiB) — yet the RPC hang persisted, twice, for a combined 390s. **The stall is not
GPU/VRAM-bound.** The process is alive and actively burning CPU (not crashed, not passively
deadlocked) but never completes whatever it's looping on, and never reaches the point of servicing
its first RPC tick. This is a livelock signature, not a render-thread stall.

**Practical implication:** Tier 2 of the C20 runbook (driver reinstall, thermal/power fixes, TDR
tuning) targets the wrong bottleneck and is unlikely to help — the GPU was never the constraint in
the `-nullrhi` runs. The real next step needs process-level introspection this environment doesn't
have readily available: attaching a debugger/Process Explorer to see exactly what the 59 threads are
looping on, checking Windows Event Viewer for a related system-level error, or testing whether this
specific CARLA 0.9.16 Windows build reproduces the same hang on a different machine (would indicate a
build/environment issue rather than something fixable here).

**Not yet tried from the original Tier 1 list:** minimal-render (`-ResX=64 -ResY=64 -windowed`) and
`-vulkan` — both still assume a render-path fix, which the `-nullrhi` result makes unlikely to help,
so they were deprioritized in favor of reporting this finding rather than continuing to guess.
