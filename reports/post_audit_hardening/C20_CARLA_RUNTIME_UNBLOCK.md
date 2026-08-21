# C20 — CARLA runtime unblock (RPC-hang root cause + tiered fix)

> **⚠ ROOT CAUSE CORRECTED (2026-08-21) — the GPU/VRAM/thermal conclusion in this doc was FALSIFIED.**
> A `-nullrhi` control run (`C20_TIER1_PROBE_20260821/FINDINGS.md`, commit `68ec1744`) held **VRAM at 0 MiB** for
> 390 s yet CARLA hung identically → the stall is **NOT** render/GPU/VRAM-bound. The 96% VRAM + 82 °C measured
> under `-RenderOffScreen` were a *symptom* of rendering, not the cause. **Actual signature: a CPU livelock** —
> process alive, 59 threads burning CPU, working-set flat, no UE log/crash (stuck before logging flushes).
> **Consequence:** Tier 2 (driver/thermal) and Tier 4 (bigger GPU) below are GPU-targeted and **misdirected**;
> the real next step is process-level introspection (thread stacks / Event Viewer / a different machine). The
> probe *evidence* below is still valid — only the *conclusion* was wrong. Tier 3 code hardening was done
> separately (commit `828d1c47`).
>
> **UPDATE (Event Viewer, `C20_GPU_TDR_20260821/FINDINGS.md`):** the machine logs **chronic GPU watchdog TDR**
> (`LiveKernelEvent 141`, hundreds/hour across 3 days, with WATCHDOG dumps). This **re-elevates a GPU driver
> clean-reinstall / GPU-health check** as the cause-directed next step — but as a *driver-stability* fix (the
> watchdog is timing out), **not** the VRAM-capacity/thermal mechanism I originally (wrongly) claimed. Net: the
> GPU/driver *is* implicated after all, via TDR; the `-nullrhi` CPU-livelock may be an additional separate
> signature. Fix belongs to the environment (driver/hardware), not CARLA/maps.

**Goal:** unblock the persistent CARLA RPC-hang that gates the live-drive + RQ2/RQ3/RQ5 perception.
This is an **environment** problem (a CPU livelock in the CARLA server), not a map or pipeline defect.

## Evidence-based diagnosis (2026-08-21 probes)

| probe | finding | rules out |
|---|---|---|
| stage 1 (live hung instance) | client 0.9.16 **==** server 0.9.16; `get_client_version()` OK; `get_server_version()` **times out** | version mismatch |
| stage 2 (clean relaunch, **default map**) | port :2000 opens in **9 s**; RPC hangs **96 s** on CARLA's *own* town | our 144 MB map, map complexity |
| session check | `console` session (not RDP) | RDP/no-GPU-context |
| GPU | Quadro **P3200 Max-Q, 6 GB VRAM**; CARLA footprint **5914/6144 MiB (96%)**; 82 °C; 70 W power cap | — |
| kill test | PowerShell `Stop-Process` kills cleanly; **VRAM frees to 0 MiB** | GPU hardware hang / VRAM leak |

**Conclusion:** TCP :2000 binds immediately, but the **UE game thread never services RPC** (CARLA processes
RPC on the game-thread tick). The GPU is healthy (killable, VRAM frees), but CARLA runs at **96 % of a 6 GB
Max-Q GPU** that is thermally/power throttled. The game thread stalls on first-frame GPU work
(shader compilation + render init + VRAM eviction thrash) so the first tick — and thus the first RPC — never
completes. `-RenderOffScreen` does **not** help because it still renders off-screen (still uses the GPU/VRAM).

### Verdict (patient probe, 480 s) — GENUINE DEADLOCK, not slowness
Clean launch (VRAM 0 at start), waited **480 s** for the first `get_server_version()`: **no RPC, ever**. VRAM
pinned at **5914 MiB (96%)** and GPU at **82 °C** for the entire 8 minutes (util oscillating 47–95%). Shader
compilation would have finished well inside that window — this is a **sustained VRAM/thermal-bound game-thread
stall**. → **Patient-wait is ruled out.** Because the stall is caused by GPU pressure, the fix must *remove the
pressure* (render-reduction / `-nullrhi` / smaller runtime footprint / driver+thermal / bigger GPU), not wait
longer. Evidence: `C20_CARLA_RUNTIME_UNBLOCK/stage3_patient.log`.

### Tooling gotcha discovered (fix in any runbook)
`taskkill /F /T /IM ...` run from **Git Bash mangles `/F` → `F:/`** and silently fails. Kill CARLA with
**PowerShell** `Stop-Process -Name CarlaUE4-Win64-Shipping -Force` (Python `subprocess.run(["taskkill",...])`
is fine — args aren't shell-mangled). Several past "unkillable / still hung" observations were this artifact.

---

## Tier 1 — config workarounds (sonnet-runnable NOW, cheapest)

The stall is GPU-pressure-bound, so these **reduce the pressure**. Run each; first that yields
`get_server_version()` wins. Kill cleanly between attempts (**PowerShell** `Stop-Process`, not Git Bash taskkill)
and verify `nvidia-smi` shows ~0 MiB before launching.

1. **`-nullrhi` (do this first)** — no rendering hardware interface, so ~0 render VRAM. If RPC comes up under
   `-nullrhi` where it deadlocked otherwise, it *confirms* render/VRAM as the cause **and** immediately unblocks
   the **live-drive gate** (physics/RPC only). Caveat: disables cameras/semantic sensors, so it does **not** do
   perception capture — but it closes the drivability gate on `69b1f520` today. Command:
   `CarlaUE4.exe -nullrhi -nosound -carla-rpc-port=2000`.
2. **Minimal render target** — for the capture path: `-RenderOffScreen -quality-level=Low -ResX=64 -ResY=64
   -nosound`. Lowest render/VRAM footprint that still produces camera frames.
3. **Vulkan RHI** — try `-vulkan` (UE4.26/CARLA supports it); DX11 vs Vulkan can differ in init deadlocks on
   mobile GPUs.
4. ~~**Patient wait**~~ — **RULED OUT** by the 480 s probe (genuine deadlock, not slowness). Do not rely on longer
   timeouts alone. (A one-time warm run to populate the shader DDC may still speed *later* launches, but does not
   fix the deadlock.)

## Tier 2 — GPU/driver hygiene (hands-on, user)

1. **Clean VRAM before every launch:** `Stop-Process -Name CarlaUE4-Win64-Shipping,CarlaUE4 -Force`; confirm
   `nvidia-smi` → memory.used ≈ 0. A leaked prior instance at 96 % guarantees the next launch fails.
2. **Free other GPU consumers** (browsers/Electron apps eat VRAM on a 6 GB card).
3. **NVIDIA driver:** current is **573.22**. Clean-reinstall (DDU → latest Quadro/NVIDIA Studio driver). A wedged
   display driver is the classic cause of a game-thread GPU stall that survives process kills but not a driver
   reset/reboot.
4. **Thermal/power:** 82 °C on a 70 W Max-Q = heavy throttling. AC power, max performance mode, cooling. A
   throttled first tick can exceed any reasonable RPC timeout.
5. **TDR:** ensure Windows GPU Timeout Detection & Recovery is at default (a too-short TDR can kill the render
   thread mid-init; a disabled TDR lets it hang forever). Registry `HKLM\System\CurrentControlSet\Control\GraphicsDrivers\TdrDelay`.

## Tier 3 — code hardening (sonnet, TDD)

These make the runtime diagnosable + resilient regardless of the GPU outcome:

1. **Stop discarding the server log.** `ultimate_pipeline/core/carla_utils.py:300-301` sends CARLA stdout/stderr
   to `DEVNULL`. Change to tee into `reports/.../carla_server_<ts>.log` (and pass UE `-log`). Every future hang
   becomes diagnosable. *(TDD: assert the launcher writes a non-empty log path into its return/telemetry.)*
2. **Configurable, longer readiness timeout.** `_wait_for_ports`/`ensure_carla_ready` default is too low for a
   slow GPU; add `UP_CARLA_READY_TIMEOUT_S` (default 600) and poll `get_server_version` (not just port).
3. **Minimal-render + nullrhi launch flags** behind env flags (`UP_CARLA_MIN_RENDER`, `UP_CARLA_NULLRHI`) so the
   drive gate can run headless-minimal without editing code.
4. **VRAM preflight.** Before launch, query `nvidia-smi memory.used`; if > ~1 GB, kill stale CARLA / warn — fail
   fast with an actionable message instead of a 10-minute hang.

## Tier 4 — the real fix (hardware/path, user)

A **6 GB Max-Q** is marginal for CARLA 0.9.16 + the enriched Ingolstadt map (5 686 buildings). Durable options,
best first:
1. **Run the perception capture on a bigger GPU** (≥ 8–12 GB) — a workstation/cloud box. This is the clean
   unblock for RQ2/RQ3 authoritative capture.
2. **UE cook path (R4/C16):** a cooked package can be lighter/more stable at runtime than live-XODR import, and is
   required anyway for `PAIRED_INGOLSTADT`. Needs the UE operator.
3. **Shrink runtime footprint:** capture on a cropped sub-map (the RQ2 route neighborhood) instead of the full
   32 k-road map — far less VRAM, still a valid paired comparison on the driven area.

---

## Remaining offline items (unrelated to CARLA; sonnet-runnable, low research-signal)
- **C13 full map-registry + drift-guard tests** — formalize `carla_tools/map_registry.py` for the pinned pair (TDD).
- **C9-tail gate positive/negative controls** — ~13 checkers lack +/- controls (verify Codex didn't already do these).

## Verification (definition of unblocked)
- `get_server_version()` returns within the timeout on the **default** map (env fixed), then on the pinned auto map.
- `scripts/drive_route_probe.py --spawns 5 --frames 240` PASS on `69b1f520` (live-drive gate closes).
- Paired capture (C17 path-A) produces non-empty `rgb/` + `semseg_raw/` on both maps → RQ2/RQ3 resume.
