# C20 addendum — chronic GPU watchdog TDR (LiveKernelEvent 141) on this machine

Event Viewer (checked 2026-08-21, the process-introspection step Sonnet's Tier-1 findings flagged as "not yet
tried") reveals a **chronic GPU/display watchdog failure** independent of any single CARLA run.

## Evidence
- **`Windows Error Reporting` → `LiveKernelEvent`, P1 = `141`** (video/display TDR — "the display driver failed to
  respond in a timely fashion"), attaching `C:\Windows\LiveKernelReports\WATCHDOG\WATCHDOG-*.dmp`.
- **Frequency:** hundreds per hour, continuously, across **3 days** (08-19 → 08-21). Sample by-hour counts:
  `199, 47, 141, 94 (08-19)`; `94, 188, 94, 47, 94, 235 (08-20)`; `94, 47, 47, 141, 94 (08-21)`.
- GPU: Quadro **P3200 Max-Q**, driver **573.22**, 6 GB, thermally/power capped (82 °C @ 70 W under load).
- The standard System-log Event 4101 ("display driver stopped responding and has recovered", provider
  `Display`/`nvlddmkm`) did **not** appear — the failures surface only as WER `LiveKernelEvent 141` watchdog
  dumps, i.e. the GPU engine timing out without a full driver reset.

## Interpretation (measured — avoids re-overclaiming)
- **Established fact:** the display/GPU watchdog is tripping chronically on this machine.
- **Strong inference:** the GPU driver (or the Max-Q GPU hardware itself) is unstable under load; CARLA, which is
  GPU-heavy, reliably drives it into the render-path hang seen under `-RenderOffScreen` (my earlier probes: VRAM
  96 %, 82 °C, no RPC).
- **Open nuance:** Sonnet's `-nullrhi` run hung with **VRAM = 0** and util ~0 % — a CPU-livelock with no GPU use.
  So a driver fix may unblock the **render/capture** path without fully explaining the `-nullrhi` livelock (UE may
  still spin on GPU-device enumeration even under `-nullrhi` when the driver is wedged). Do not claim the TDR is
  the sole cause of every observed hang.

## Actionable fix (cause-directed, hands-on — supersedes C20 Tier 2's rationale)
1. **GPU driver clean-reinstall:** DDU (Display Driver Uninstaller) in safe mode → install a **known-stable**
   NVIDIA driver for the Quadro P3200 (consider rolling **back** from 573.22; test one prior branch). This
   directly targets the watchdog TDR.
2. **GPU hardware health:** the constant watchdog trips + 82 °C on a mobile Max-Q may indicate degradation or
   thermal/power delivery issues. Check with a GPU stress/health tool; reseat/repaste if thermals are the driver.
   If TDRs persist on a clean driver, suspect failing hardware → use a different machine (as Sonnet suggested).
3. **Re-test CARLA only after the 141 stream stops** (verify via Event Viewer that new LiveKernelEvents cease at
   idle), then re-run the `-RenderOffScreen` patient probe and the live-drive gate.

## Bottom line
This is an **environment/hardware fault on this machine**, not a CARLA, map, or pipeline defect. The maps
(`69b1f520`, `Grid0828`) remain fully exonerated. Perception RQ2/RQ3 realistically need either a driver fix that
stops the TDR stream **or** a different GPU/machine.

## Runtime guard
Follow-up hardening added a CARLA lifecycle preflight for recent Windows `LiveKernelEvent 141` records. CARLA
launch/connect now fails closed when the TDR stream is present, so future live evidence cannot silently run on this
known-bad GPU state. See `RUNTIME_GUARD.md`.
