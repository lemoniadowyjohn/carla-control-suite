# M5B — Full Cook Execution Spec

**Entry precondition: `RUNTIME_HOST_ADMISSION=PASS`.**

Do not begin any step in this document until `RUNTIME_HOST_PREFLIGHT.ps1` has emitted
all five gates as `PASS` on **this** host. An admitted host that later changes state
(cleanup, driver update, security policy change, reboot with different config) is
**re-admitted or not at all** — re-run the preflight.

Current host status: `DENIED_EXTERNAL`. This spec is written for another machine.

---

## 0. Scope and honesty boundary

This spec produces a **cooked map package**. It does **not** produce runtime evidence.
Keep these separate and never let one imply the other:

| Stage | Produces |
| --- | --- |
| M5B (this spec) | cooked package on disk |
| M6 (`M6_EXECUTION_SPEC.md`) | live RPC-backed runtime evidence |

A completed cook is **not** a runtime pass. A runtime pass is **not** a capture pass.

## 1. Authoritative inputs

Resolve the map of record **via the registry**. Never by mtime, glob, or "newest file".

| Input | Identity |
| --- | --- |
| Registry key | `auto_map_of_record` |
| Map of record | `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr` |
| SHA-256 | `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8` |
| Source OSM SHA-256 | `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f` |
| Import package | `Ingolstadt`, 20 tiles, tile size 1000.0 m, grid x6–10 × y6–9 |
| Tile manifest | `Import/Ingolstadt/PACKAGE_SHA256.json` (`status: verified`, 21 files) |
| CARLA source | `294096eb1c38eabf246e4f3a9cdab704e33a7f4c` (tag `0.9.16`) |
| UE source | `e9d9e60c85f643e10eeb03f42f61554d18dcb30f` (branch `carla`, UE 4.26) |
| Python client | `carla==0.9.16` |

> **Re-verify the CARLA source SHA against your own checkout before starting.** In-repo
> provenance for it is contested — one receipt records it as `unknown`/`null` and a
> results file states it was never found, with the tag merely inferred. Two in-repo
> sources disagree. Do not start an expensive cook on an unverified pin.

## 2. Cook configuration — resolve before starting

**Cook configuration is NOT established.** Do not assert "Shipping". In-repo, every
recorded UE4 target is `Win64 Development`, and the cook-configuration receipt field is
`null`/`unknown`. Establish it on this host, record it, and pin it in this run's evidence.

| Field | Value |
| --- | --- |
| `CARLA_VERSION` | `0.9.16` |
| `UNREAL_VERSION` | `4.26` |
| `TARGET_PLATFORM` | Windows (runtime host) — cook may be Linux/Docker, see §8 |
| `COOK_CONFIGURATION` | **UNRESOLVED — operator must determine and record** |

## 3. Pre-cook gate (all must hold)

| Gate | Requirement |
| --- | --- |
| Host admission | `RUNTIME_HOST_ADMISSION=PASS` from this host |
| System volume free | ≥ **20 GB** |
| Work volume free | ≥ **12 GB** |
| Engine volume free | ≥ **45 GB** |
| Total reserve | DDC 25 GB + cook output 20 GB + safety 10 GB = **55 GB** |
| Physical RAM | ≥ 32 GB recommended |
| **Commit limit** | ≥ **70 GB** (hard) |
| Pagefile | must be expandable or pre-sized; a starves-your-commit host cannot cook |
| `MemoryMaxUsedVirtual` | `30500` MiB — **verify it is finite and took effect** |
| `MemoryMaxUsedPhysical` | `16384` MiB |
| `MemoryMinFreePhysical` / `MemoryMinFreeVirtual` | `2048` / `4096` MiB |
| TargetedRHIs | `PCD3D_SM5` + `SF_VULKAN_SM5` present; **`PCD3D_ES31` absent** |
| Runtime shader failures | `0` |
| Content layout | CARLA content resolves under `/Game/Carla/*` |
| No orphan `UE4Editor.exe` | none holding Content locks |
| No active cook lease | single-writer; no other cook running |

**Re-measure free space immediately before starting.** The generating host's baseline
drifted 1.8 GB within minutes with no deletion, so cached measurements are unsafe.

Enforce with: `python tools/unreal_cook_resource_preflight.py --json-out <out.json>`
(report-only; exit `0` PASS / `2` BLOCKED / `3` INCOMPLETE) and
`python tools/check_windows_rhi_scope.py <path/to/DefaultEngine.ini>`.

Note the in-repo storage gates are marked **`NOT YET IMPLEMENTED`** — nothing enforces
them in code. The preflight script enforces them explicitly. Do not assume coverage.

## 4. DDC configuration

Local **NVMe**, **> 50 % free**, **no junction/symlink layer**, not the system drive.
Random read ≥ 500 MB/s, median latency < 0.5 ms (qualified by preflight step 6).

```ini
[/Script/Engine.DerivedDataCacheSettings]
+Root=(Type=KeyLength, Length=120, Inner=Pak)
+Root=(Type=FileSystem, ReadOnly=false, Clean=false, Flush=false, DeleteUnused=false, UnusedFileAge=30, MaxSizeMB=51200, Path="<FAST_NVME_PATH>\DDC", EnvPathOverride="UE4_DDC")
+Root=(Type=KeyLength, Length=120, Inner=Pak)
+Root=(Type=FileSystem, ReadOnly=true, Clean=false, Flush=false, Path="<READONLY_SHARED_DDC>")
```

**Resolve the in-repo contradiction first.** `DDC_TARGET_SELECTION.json` nominates one
drive on small-file throughput; `COOK_CAPACITY_MODEL.json` rules that same drive out on
capacity and recommends another. Pick from **both** criteria, or relocate DDC and cook
output to separate volumes. Do not copy either drive letter forward.

**Never purge an existing DDC before its evidence is preserved.** A degraded DDC
(`0.00–0.08 MB/s`) is itself evidence of a real, documented defect.

## 5. Command template

### 5a. Import (if the package is not yet imported)

```bash
# Validate the staged package first. Never import a package that has not passed.
python tools/preflight_import_package.py \
  --package-dir Import/Ingolstadt \
  --expected-tile-size 1000.0 \
  --expected-xodr-sha 370abbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8 \
  --json-out reports/m5b_import_preflight.json \
  --human-readable
# Emits READY_FOR_IMPORT | BLOCKED_FOR_IMPORT | INCOMPLETE_FOR_IMPORT
# It deliberately never claims READY_FOR_RUNTIME. Do not upgrade that claim.

cd "$UE4_ROOT/Engine/Build/BatchFiles"
# Linux: RunUAT.sh   |   Windows: RunUAT.bat / Build.bat
RunUAT BuildCookRun \
  -project="$CARLA_ROOT/CarlaUE4/CarlaUE4.uproject" \
  -noP4 -utf8output \
  -map="$CARLA_ROOT/Content/Ingolstadt" \
  -clientconfig=Shipping \
  -cook -stage -pak -iterate \
  -targetplatform=Windows \
  -unversionedcookedcontent \
  -fileopenlog
```

### 5b. Cook only (package already imported)

```bash
python tools/unreal_cook_resource_preflight.py --json-out reports/m5b_cook_preflight.json
python tools/check_windows_rhi_scope.py "$CARLA_ROOT/Unreal/CarlaUE4/Config/DefaultEngine.ini"

cd "$UE4_ROOT/Engine/Build/BatchFiles"
RunUAT BuildCookRun \
  -project="$CARLA_ROOT/CarlaUE4/CarlaUE4.uproject" \
  -noP4 -utf8output \
  -map="$CARLA_ROOT/Content/Ingolstadt" \
  -clientconfig=Shipping \
  -cook -stage -pak -iterate \
  -targetplatform=Windows \
  -unversionedcookedcontent \
  -fileopenlog
```

**Replace `<...>` placeholders from the environment. Do not hard-code a drive letter or
an absolute path into any committed file.**

### 5c. Resource census (observe, do not manage)

```bash
python tools/cook_diagnostics/cook_resource_census.py --pid <COOK_PID> --interval-sec 15
```

Read-only observer — it does **not** launch or manage the cook. It samples
`committed_bytes`, `commit_limit`, `percent_used`. It carries **no thresholds**, so it
will not stop a failing cook; you must watch it yourself. Start it before the cook.

## 6. Cook parameterization

| Parameter | Value | Note |
| --- | --- | --- |
| Map | `Ingolstadt` | one logical map, one authoritative XODR |
| Tile size | 1000.0 m | must match the staged package |
| Tiles | 20 | grid x6–10 × y6–9 |
| `-cook` | yes | |
| `-stage` `-pak` | yes | |
| `-iterate` | yes | only against a warm DDC |
| `-targetplatform` | `Windows` | matches runtime host |
| Coordinate authority | reuse governed transform, do **not** re-derive | |
| CRS | `+proj=tmerc +datum=WGS84 +units=m +no_defs` | |
| UE target frame | cm, LH, X-fwd / Y-right / Z-up | |
| Visible-road authority | `CARLA_GENERATED_ROAD` | OSM2World/Blender roads are **quarantined** from visible-road authority |

**Track discipline:** UE4/`make` only. UE5, CMake/Ninja, World Partition, Nanite, Lumen,
and virtual textures are **disabled**. Do not mix UE4 and UE5 paths.

**Bounded batches:** one map name, one authoritative XODR, bounded batches. Do not
promote a partially cooked map to release authority.

## 7. Evidence to record

Record all of it in machine-readable manifests. A cook without evidence is not a result.

| Item | Notes |
| --- | --- |
| Host admission report | all five gates `PASS`, this host, this run |
| CARLA source commit | re-verified locally |
| UE source commit + version | 4.26.x, branch, and the provenance caveat |
| `DefaultEngine.ini` SHA-256 | and its TargetedRHIs |
| Map-of-record SHA-256 | and tile manifest verification (21/21) |
| Cook configuration | the resolved value — currently unresolved in-repo |
| Cook log | full, with `-fileopenlog` |
| Package set | file list + per-package SHA-256 |
| Wall clock | and DDC hit/miss counts |
| Census CSV | commit % over time; peak |
| Memory settings as applied | prove `MemoryMaxUsedVirtual` was finite and took effect |
| Terminator | how the cook ended (completed / stalled / killed) — say which |

**If the cook stalls, that is the result.** Do not relabel it as partial success, do not
lower a threshold to make it fit, and do not purge the DDC. A generating-host cook ran
~14 h 52 min to 82.7 % and then stalled — that host had a 100 %-saturated commit limit,
a 9 GB pagefile, and an external-HDD DDC reading `0.00–0.08 MB/s`. Diagnose the resource
condition; do not retry blindly.

## 8. Linux cook path (optional alternative)

CARLA 0.9.16 binary ingestion is Linux/Docker-native; the Windows host must prove a
WSL2/Linux path. A Windows host may run the **runtime** while a Linux host runs the
**cook**, provided both agree on CARLA `0.9.16`, UE `4.26`, TargetedRHIs, and the
map/tile hashes above.

**No Docker image digest is recorded anywhere in the repo** — only requirements to record
one. If you build a container, record its digest and pin it. Do not invent one.

## 9. M5B exit criteria

| # | Criterion |
| --- | --- |
| 1 | `RUNTIME_HOST_ADMISSION=PASS` from this host, this run |
| 2 | Cook terminated **naturally** (not killed) |
| 3 | Package set written and per-package SHA-256 recorded |
| 4 | Map present in the **runtime** cook registry — verified, not assumed |
| 5 | `TARGETED_RHIS_OK`, `PCD3D_ES31` absent, 0 runtime shader failures |
| 6 | DDC hit rate and wall clock recorded |
| 7 | No orphaned `UE4Editor.exe` / `ShaderCompileWorker.exe` remaining |
| 8 | All §7 evidence written |

**Criterion 4 is the one most often assumed.** The authoritative map is currently
`BLOCKED_COOK_REQUIRED` — absent from the live runtime's cook registry (0 of 15 maps). A
successful cook on disk does not by itself place the map in the runtime registry.
Verify against the runtime's map list, then promote — never promote on the strength of
the cook log alone.

On success, proceed to `M6_EXECUTION_SPEC.md`. **M5B alone is not a runtime pass.**
