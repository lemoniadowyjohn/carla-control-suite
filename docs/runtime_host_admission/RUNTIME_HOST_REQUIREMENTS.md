# Runtime Host Admission Kit — Requirements

**CURRENT_HOST_RUNTIME_ADMISSION=DENIED_EXTERNAL**

This document and its siblings are a **portable admission kit** to be executed on a
*different* Windows or Linux machine. Nothing here was executed against Unreal or CARLA
on the host that generated it. The generating host is runtime-denied and its three
blockers are treated as **accepted and out of scope**:

| Accepted blocker | Nature |
| --- | --- |
| `GPU_DRIVER_RENDER_STALL` | Hardware/driver fault on the generating host. Maps and pipeline exonerated. |
| `NULLRHI_LIVELOCK` | CPU-side livelock; process alive, VRAM flat at 0 MiB, never reaches RPC servicing. |
| `AVAST_UE4EDITOR_QUARANTINE` | Endpoint security removed the editor binary. Path-specific, not filename-specific. |

**The generating host is not qualified and must never be reported as qualified.**
These three blockers are host properties. They do not transfer, and their absence
elsewhere does not qualify anywhere either.

## Governing rule

> **An editor window opening is not qualification.**

`RUNTIME_HOST_ADMISSION=PASS` is emitted only when **all five** gates below are `PASS`
from the ordered preflight, on the new host, with evidence recorded. See
`RUNTIME_HOST_PREFLIGHT.ps1`.

| Gate | Meaning |
| --- | --- |
| `UE_EDITOR_SMOKE=PASS` | Editor starts, initializes, and exits cleanly (no hang, no orphan). |
| `SCW_SMOKE=PASS` | `ShaderCompileWorker.exe` launches and responds. |
| `AV_EXCLUSION_OR_NONINTERFERENCE=PASS` | Endpoint security neither quarantines nor blocks engine binaries. |
| `DDC_QUALIFIED=PASS` | DDC meets read-latency and throughput targets. |
| `CARLA_RPC_SMOKE=PASS` | Packaged server answers a real RPC round-trip. |

**Order matters.** The preflight is strictly sequential and stops at the first failure.
A port being open is **not** CARLA success — success is an actual RPC response
(`client.get_server_version()` returning a value). Never delete an exclusion to make a
gate pass; never bypass endpoint security.

## Provenance and pins

> **Read this before trusting any SHA below.** Two pins are *not* reproducible-quality
> guarantees. See "Provenance limitations" at the end.

### Source pins

| Item | Value |
| --- | --- |
| CARLA version | **0.9.16** (required; client must match server) |
| CARLA source commit | `294096eb1c38eabf246e4f3a9cdab704e33a7f4c` |
| CARLA source remote | `https://github.com/carla-simulator/carla.git` (tag `0.9.16`) |
| Unreal version | **4.26** (build reports 4.26.2, branch `++UE4+Release-4.26`) |
| UE source commit | `e9d9e60c85f643e10eeb03f42f61554d18dcb30f` |
| UE source remote | `https://github.com/CarlaUnreal/UnrealEngine.git` (branch `carla`) |
| Engine patch check | `Engine/Shaders/Private/CARLA/{CopyCustomStencil,CopySceneDepth,CopySceneStencil,CopyVelocity}.usf` present |

CARLA 0.9.16 requires UE 4.26. Do **not** mix UE4 and UE5 paths.

### Client / server

| Item | Value |
| --- | --- |
| Python client | `carla==0.9.16` |
| RPC version check | `client.get_server_version()` must return `0.9.16` |

**Known gap — the version gate is not fail-closed in-repo.** Existing preflight records
`get_server_version()` and continues on failure, and emits only an advisory warning on
client/server mismatch. `RUNTIME_HOST_PREFLIGHT.ps1` therefore **explicitly** compares
both and fails the gate. Do not rely on upstream tooling for this check.

### Ports

| Port | Role |
| --- | --- |
| 2000 | RPC |
| 2001 | Streaming |
| 2002 | Secondary |

Client host is `127.0.0.1` in all first-party tooling. **Do not hard-code the port** in
new work — use `UP_CARLA_RPC_PORT` / `UP_CARLA_STREAMING_PORT`. Protocol/transport
annotations were never recorded in-repo, so confirm the transport on the new host rather
than assuming it.

### Binary identity expectations (advisory)

Recorded from the generating host. Because that host's engine build is not
reproducibly pinnable (see limitations), treat these as **informational**, and
re-baseline them on the new host rather than failing the build on mismatch.

| Binary | SHA-256 |
| --- | --- |
| `UE4Editor.exe` | `05DC57656EAC65FE0A4867ABA853155BB83D48F08D5B77DF164901E8B0D72134` |
| `UE4Editor-Cmd.exe` | `A34853EB703129570D75E9183890AA00BD38F795590E87436FC3E1B5CF656601` |
| `ShaderCompileWorker.exe` | `3B84E9B7DF824D67B468BB5A6CD7E2DA63203EFC80C3FD58B4E3D7796FAC2129` |
| `UnrealHeaderTool.exe` | `03EF36E5AE346D4BA13B84FA9F59BC91B5DCAD930025EC245F21A63CF39981E2` |
| `UE4Editor-Carla.dll` | `2BB26F6BE0FE450C93E79F69EED8828EDFABCD5CA72143119BBDD7A308106139` |
| `UE4Editor-CarlaTools.dll` | `702EB5DBC406B90113AD134E4C5B4BA0CD02E4872D4EFFD2498E64B961E79D65` |
| `UE4Editor-CarlaExporter.dll` | `A3EBB88BCEFD7DE55169B390C87AC4DA135249B20D501A5603EDA93A9BA7DA10` |
| `UE4Editor-CarlaUE4.dll` | `62EC5A045B07DE99A1E9C07513BE90F17F27644E0817E81EAEF695A9C2D11B38` |

Note: `ShaderCompileWorker.exe` is **byte-identical to `XGEControlWorker.exe`** by
design in this engine build (UE4 copies SCW post-build). This is expected and is **not**
evidence of a stub binary.

**Not recorded, therefore not verifiable in this kit:** LibCarla `.lib` SHA-256,
`CarlaPythonAPI` identity, and SHA-256 for `StreetMapRuntime` / `StreetMapImporting`
plugins. Treat their absence as an open item, not a pass.

### Cook configuration

| Item | Value |
| --- | --- |
| Cook configuration | **UNRESOLVED — do not assert** |
| Engine targets actually built | `Win64 Development` (all five targets) |
| Packaged runtime binary | `CarlaUE4-Win64-Shipping.exe` |

The in-repo cook-configuration field is `null`/`unknown`, and every recorded UE4 target is
`Win64 Development`, not Shipping. **Do not write "Shipping" into a kit as though it were
established.** Determine and record it on the new host.

### TargetedRHIs

| Item | Value |
| --- | --- |
| Required Windows TargetedRHIs | `PCD3D_SM5`, `SF_VULKAN_SM5` |
| `DefaultGraphicsRHI` | `DefaultGraphicsRHI_DX12` |
| Forbidden | `PCD3D_ES31` must be absent |
| Required runtime shader failures | `0` |
| Reference `DefaultEngine.ini` SHA-256 | `a29b289a289d64fec961ee577da4fd6b6b13365cbcf5bc54cc5b71c63a7ebc92` |

`PCD3D_ES31` must be removed — it produced `ShadingModel MSM_Hair not supported in feature
level ES3_1` failures during cook. Note the in-repo gate script hard-requires only
`PCD3D_SM5`; it does **not** enforce `SF_VULKAN_SM5`. Validate both yourself.

Watch for UE ini semantics: a bare `-TargetedRHIs=X` line **resets** the list, while
`+TargetedRHIs=` appends.

### DDC policy

| Policy | Requirement |
| --- | --- |
| Read throughput | **≥ 500 MB/s** |
| Read latency | **< 0.5 ms** |
| Warm vs cold shader-compile reduction | **≥ 90 %** |
| Wall-clock reduction | **≥ 50 %** |
| Placement | Local **NVMe**, **> 50 % free**, **no junction/symlink layer**, not the system drive |
| Cache size | `MaxSizeMB=51200`, `UnusedFileAge=30` |

Hierarchy: **writable local root first, read-only shared fallback second.**

```ini
[/Script/Engine.DerivedDataCacheSettings]
+Root=(Type=KeyLength, Length=120, Inner=Pak)
+Root=(Type=FileSystem, ReadOnly=false, Clean=false, Flush=false, DeleteUnused=false, UnusedFileAge=30, MaxSizeMB=51200, Path="<FAST_NVME_PATH>\DDC", EnvPathOverride="UE4_DDC")
+Root=(Type=FileSystem, ReadOnly=true, Clean=false, Flush=false, Path="<EXISTING_DDC_PATH>")
```

**Known trap.** The in-repo DDC recommendation is **self-contradictory**: the throughput
selection names one drive, while the capacity model rules that same drive out and
recommends another. Resolve placement on the new host from *both* throughput **and**
capacity before committing. Do not carry either drive letter forward.

**Never purge an existing DDC before its evidence is preserved.** Degraded DDC
(`0.00–0.08 MB/s`) is itself evidence.

### Disk capacity

Reserves: DDC **25 GB** + bounded cook output **20 GB** + safety **10 GB** = **55 GB**
minimum, and that is a **lower bound** derived on a stalled run.

| Class | Min free |
| --- | --- |
| Import | 12 / 8 / 30 GB (system / work / engine volumes) |
| Cook | 20 / 12 / 45 GB (system / work / engine volumes) |

These in-repo gate thresholds are marked **`NOT YET IMPLEMENTED`** — no code enforces
them. `RUNTIME_HOST_PREFLIGHT.ps1` implements them explicitly. Re-measure free space
immediately before cleanup; the generating host's baseline drifted 1.8 GB in minutes with
no deletion, so its projections carried unquantified downside risk.

### RAM / pagefile / commit headroom

Recommended editor memory settings:

| Setting | Value |
| --- | --- |
| `MemoryMaxUsedPhysical` | `16384` MiB |
| `MemoryMaxUsedVirtual` | `30500` MiB |
| `MemoryMinFreePhysical` | `2048` MiB |
| `MemoryMinFreeVirtual` | `4096` MiB |

**Hard requirement:** commit limit ≥ **70 GB**.

**Critical:** `ShaderCompileWorker` processes are spawned **separately** and are *not*
counted in the editor's memory accounting — each worker can use 1–4+ GB. A host can look
fine and still die on commit exhaustion. Budget ≈ 2.0 GB per worker
(4 workers ≈ 8.0 GB aggregate) on top of editor peak virtual (≈ 12.5 GB).

**These settings only work if the virtual limit is actually finite.** A recorded host had
`MemoryMaxUsedVirtual=0` (unlimited), which disables commit throttling entirely. Verify
the value took effect before starting any cook.

If the limit is still hit, reduce SCW count via
`DevOptions.Shaders.NumUnusedShaderCompilingThreads` **before** lowering the virtual cap.

The generating host ran 9 GB pagefile at **100 % commit saturation** with no expansion
possible. A starves-your-commit host cannot run a cook, regardless of free disk.

### Map and source hashes

| Item | Value |
| --- | --- |
| Map of record | `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr` |
| Map-of-record SHA-256 | `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8` |
| Registry key | `auto_map_of_record` |
| Size / frame | 149799632 B / `rebased_local`, dx `832671.676`, dy `5458671.104` |
| Source OSM SHA-256 | `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f` |
| CRS | `+proj=tmerc +datum=WGS84 +units=m +no_defs` |
| Package | `Ingolstadt`, tile size 1000.0 m, **20 tiles**, grid x6–10 × y6–9 |
| Tile manifest | `Import/Ingolstadt/PACKAGE_SHA256.json` (21 files, `status: verified`) |

Resolve the map of record **via the registry**, never by mtime or glob.

**Runtime identity caveat — read this.** The authoritative map is currently
`BLOCKED_COOK_REQUIRED`: it is **absent from the live CARLA 0.9.16 runtime's cook
registry** (0 of 15 maps present). The only established runtime identity is the manual
package `Grid0828` (`RUNTIME_IDENTITY_ESTABLISHED`). So on arrival of a new host,
expect **`Ingolstadt` to be un-cooked**. A successful `UE_EDITOR_SMOKE` does not mean
`Ingolstadt` exists at runtime.

Also note: `AUTO_COOK_RECEIPT.json` is an **offline FBX-generation record, not a cook
receipt**. No editor was invoked. Do not read `status: PASS` there as a cook success.

## Provenance limitations (carry into the new host)

These are **not** caveats to skim — they bound what this kit can claim.

1. **The UE pin is not a reproducibility guarantee.** Depth-1 (shallow) clone; the tip
   commit is a *local* VS2026-compatibility patch, not an official release-branch commit;
   upstream provenance beyond the tip cannot be verified locally. Recorded expectation:
   binary output **may not be bit-identical** to the engine that produced the packaged
   Shipping runtime.
2. **The UE fork may be inaccessible.** `git ls-remote` against the engine fork returned
   `Repository not found (128)` — an Epic account/org-membership issue. A new host may be
   unable to fetch the engine at all. Resolve access **before** scheduling.
3. **CARLA source SHA provenance is contested.** One receipt records CARLA/UE commit and
   tag all as `unknown`/`null`, and a results file states the SHA was *not found*, with the
   tag inferred only. The SHA above comes from a different artifact. **Re-verify it against
   your own checkout** rather than trusting either record.
4. **No Docker image digest is recorded anywhere.** Only requirements to record one. Do not
   invent one.
5. **Cook configuration is unresolved** (see above).
6. **Numeric capacity/memory figures are host-specific lower bounds** measured on a
   GPU-TDR-affected, commit-saturated, pagefile-starved host.
7. **Readiness ≠ build ≠ runtime.** Keep these six states separate on the new host:
   engine editor present, project compiled, server binary present, RPC responsive, map
   cooked, map loadable. Never let one imply another.
8. **All threshold-derived artifacts in-repo are advisory.** Re-derive on the new host.

## Content layout requirement

CARLA content must resolve under `/Game/Carla/*`. If it does not, the editor dies with a
missing `RoadPainterPreset` Blueprint. The recorded workaround was five NTFS junctions
(`Blueprints`, `Config`, `Maps`, `Static`, `HDMaps`). **Prefer fixing the layout at the
source** rather than reproducing junctions blindly. ~43 204 assets / ~23 925 MB.

## Process discipline

- **Never** issue a global `taskkill` by image name — it can kill another operator's
  runtime. Terminate only PIDs you own.
- **Never** use `taskkill` from Git Bash: `/F` is mangled to `F:/` and the command fails
  silently. Past "unkillable process" incidents were this artifact, not a hung process.
- Orphaned `UE4Editor.exe` processes have survived ~25 minutes after their parent exited
  and can hold Content-tree file locks that break a later cook. Check for orphans before
  starting work.
- The offline CI workflow reports runtime verification as `NOT_RUN` by design. Only the
  self-hosted runtime workflow may claim live evidence.
- Sync-mode note: a crashed owner can leak `synchronous_mode=True` and block later RPC.
  Do not call `load_world()` with sync mode unless a live tick owner exists.

## Kit contents

| File | Purpose |
| --- | --- |
| `RUNTIME_HOST_REQUIREMENTS.md` | This document — pins, policy, thresholds, limitations. |
| `RUNTIME_HOST_PREFLIGHT.ps1` | Ordered 8-step preflight; emits the five gates. |
| `M5B_EXECUTION_SPEC.md` | Full-cook execution spec, to run **only** after all five gates pass. |
| `M6_EXECUTION_SPEC.md` | Runtime execution spec for live capture on the admitted host. |

**No secrets and no private absolute paths.** All locations are environment variables or
placeholders. Substitute real paths only in a local, uncommitted `.env` on the new host.

## Operational hazards carried forward

- GPU TDR presented as `LiveKernelEvent` code **141** at high frequency, with **no**
  standard System Event 4101 — failures surfaced only as watchdog dumps. Detection must
  query the watchdog event stream directly.
- If `141` persists after a clean driver rollback, the machine is unsuitable; move capture
  to different hardware. Do not keep retrying.
- Antivirus remediation is UI-only in the recorded case (protection → shielding →
  exclusions) and self-defense can block registry writes even as administrator. If an
  exclusion cannot be created through documented, authorized means, **move to another
  host** rather than weakening security.
