# GAP-017 (RPC listener vs UE4 log-subsystem init) and package-2975 cook-stall diagnostics

- Classification: INTERNAL — RUNBOOK EVIDENCE
- Date: 2026-10-08
- Scope: read-only. No `CarlaUE4.exe` / `UE4Editor.exe` / `UE4Editor-Cmd` / `RunUAT` / cook process was launched. No source, config, map, XODR, receipt or `MASTER_GAP_REGISTER.json` was modified. The only file created is this report.
- Time base: host local time is UTC+02:00. All `*_YYYYMMDDTHHMMSSZ.log` filenames are UTC; all filesystem `LastWriteTime` values below are local.

---

## Part A — GAP-017: does the RPC listener start before UE4 log-subsystem init?

### A.1 Question as recorded

`MASTER_GAP_REGISTER.json` GAP-017 (2026-10-08 live attempt) states, after `CarlaUE4-Win64-Shipping.exe` (PID 47484) bound ports 2000/2001 while `get_server_version()` timed out at 60 s, 1004 CPU-seconds across ~4 threads in <7 min, `CarlaUE4\Saved\` holding zero new files and stdout/stderr redirects at 0 bytes:

> "So the engine is spinning real CPU on multiple threads before it ever reaches the point of opening its own log file, and never reaches the point of answering RPC — this points away from a late-stage rendering/GPU hang and toward something earlier in engine init (asset registration, or a blocking I/O wait implemented as a busy-loop)."

### A.2 Finding — the premise is falsified

**The 2026-10-08 binary never opens a log file at all, in any circumstance. Absence of log output therefore carries no information about how far init progressed.** The observed artefacts are the expected signature of a `NO_LOGGING` (Shipping) build, and the process demonstrably got *past* log-device setup.

Two independent errors compounded: a Shipping `NO_LOGGING` build, and inspection of the wrong `Saved` directory.

### A.3 Evidence chain

**1. The build is Shipping and `NO_LOGGING` is 1.**

| Step | Citation |
| --- | --- |
| Binary observed: `CarlaUE4-Win64-Shipping.exe` | GAP-017 register entry, 2026-10-08 attempt |
| Package script forces Shipping: `set PACKAGE_CONFIG=Shipping` (used at `:178`, `:194`) | `G:\CARLA\carla_source_probe\Util\BuildTools\Package.bat:33` |
| Target file never sets `bUseLoggingInShipping` (whole file, 35 lines) | `G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Source\CarlaUE4.Target.cs` |
| `USE_LOGGING_IN_SHIPPING` defaults to 0 | `G:\UnrealEngine_4.26_CARLA\Engine\Source\Runtime\Core\Public\Misc\Build.h:178-181` |
| Under `#elif UE_BUILD_SHIPPING` / `#else`: `#define NO_LOGGING !USE_LOGGING_IN_SHIPPING` → 1 | `Build.h:291-335` (esp. `:334`) |
| `#if NO_LOGGING` → `UE_LOG` only acts when `Verbosity == ELogVerbosity::Fatal` | `Engine\Source\Runtime\Core\Public\Logging\LogMacros.h:99-114` |
| `UE_CLOG` likewise Fatal-only | `LogMacros.h:119-127` |

**2. Log-file creation itself is compiled out — no `CarlaUE4.log` can exist.**

`FOutputDeviceFile::FOutputDeviceFile(..., bCreateWriterLazily)`:

```
OutputDeviceFile.cpp:306
#if ALLOW_LOG_FILE && !NO_LOGGING
	if (!bCreateWriterLazily) // Should the file created/opened immediately?
	{
		CreateWriter();
	}
#endif
```

`ALLOW_LOG_FILE` defaults to 1 (`OutputDeviceFile.cpp:31-32`), but `NO_LOGGING` is 1, so `CreateWriter()` is **removed by the preprocessor**. `FOutputDeviceFile::Serialize` is guarded by the same expression at `OutputDeviceFile.cpp:479`. `SetupOutputDevices()` itself is *not* guarded (`GenericPlatformOutputDevices.cpp:20-24` calls `InitDefaultOutputDeviceFile()` unconditionally; only the console/debug devices at `:36-49` are `#if !NO_LOGGING`), so the `FOutputDeviceFile` object is constructed but creates no file.

Consequence: both "zero new files under `Saved`" and "0-byte stdout redirect" are **guaranteed by configuration**, independent of init progress. The stdout side is doubly guaranteed — no `-stdout` flag was on the 10-08 command line, so `FOutputDeviceStdOutput` is not registered either.

**3. The wrong `Saved` directory was inspected.**

`FPaths::ProjectLogDir()` returns `ProjectSavedDir() + "Logs/"` (`G:\UnrealEngine_4.26_CARLA\Engine\Source\Runtime\Core\Private\Misc\Paths.cpp:420-447`, Windows branch `:447`), and `ProjectSavedDir()` is `GetSavedDirSuffix(FPaths::ProjectUserDir(), ...)` → `ProjectUserDir()/Saved/` (`Paths.cpp:71-101`).

For this packaged build the resolved tree is `C:\Users\admin\AppData\Local\CarlaUE4\Saved\`, proven by the crash-context path:

- `FGenericCrashContext::GetCrashConfigFolder()` = `FPaths::GeneratedConfigDir()/"CrashReportClient"` (`Engine\Source\Runtime\Core\Private\GenericPlatform\GenericPlatformCrashContext.cpp:938-946`)
- `GeneratedConfigDir()` = `ProjectSavedDir() + "Config/"` (`Paths.cpp:386-392`)
- On disk: `C:\Users\admin\AppData\Local\CarlaUE4\Saved\Config\CrashReportClient\UE4CC-Windows-6078D2104215D72FA48DA495BAC1F7E5\CrashReportClient.ini`, written **2026-10-08 01:10:45** (112 bytes, `[CrashReportClient] bHideLogFilesOption=false / bIsAllowedToCloseWithoutSending=true / CrashConfigPurgeDays=2`)
- Same tree: `Saved\Config\WindowsNoEditor\Engine.ini` written **2026-10-08 01:10:46** (1753 bytes)

By contrast `E:\CARLA\CARLA_0.9.16\CarlaUE4\Saved\` (the directory the register checked) last changed **2026-09-16 18:16:37** and its `Saved\Logs` child is an empty directory; a recursive scan of `E:\CARLA\CARLA_0.9.16` for files modified on/after 2026-10-07 returns exactly two entries — `carla_stdout_new.log` (0 bytes) and `carla_stderr_new.log` (0 bytes), both **2026-10-08 01:10:44** — i.e. only the harness redirects.

A filesystem-wide search for `CarlaUE4.log` / `UE4.log` under `C:\Users\admin\AppData\{Local,Roaming,LocalLow}`, `G:\CARLA`, `G:\UnrealEngine_4.26_CARLA\Engine\Saved` and the project tree found only:

- `G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Saved\Logs\CarlaUE4.log` — 2026-10-07 23:31:29, 960 223 B (the *editor* project log, unrelated)
- `G:\UnrealEngine_4.26_CARLA\Engine\Saved\Logs\UE4.log` — 2026-10-08 00:44:18, 12 273 B (engine log, unrelated)

`%LOCALAPPDATA%\CarlaUE4\Saved\Logs` directory mtime is still **2026-01-24 02:39:06** with **0 children** — no file was ever added or removed there, consistent with finding 2.

**4. Positive proof the process passed log-device setup.**

Boot order:

```
Launch.cpp:93   GuardedMain
Launch.cpp:127    -> EnginePreInit
LaunchEngineLoop.cpp:1409  FEngineLoop::PreInitPreStartupScreen
LaunchEngineLoop.cpp:2180    -> AppInit()
LaunchEngineLoop.cpp:5279      FEngineLoop::AppInit()
LaunchEngineLoop.cpp:5299        -> FPlatformApplicationMisc::PreInit()
LaunchEngineLoop.cpp:5346        MakeDirectory(FPaths::ProjectLogDir())
LaunchEngineLoop.cpp:5354        -> FPlatformOutputDevices::SetupOutputDevices()   <-- log device created here
LaunchEngineLoop.cpp:5373        -> FConfigCacheIni::InitializeConfigSystem()
LaunchEngineLoop.cpp:5381-5384   -> LoadModulesForProject / LoadModulesForEnabledPlugins  <-- Carla plugin code first reachable here
```

The `Saved\Config\CrashReportClient\UE4CC-*` file is written from `FGenericCrashContext::InitializeFromConfig()` (`GenericPlatformCrashContext.cpp:369-389`, `CrashConfigFile.Write(...)` at `:388`), which is bound to `FCoreDelegates::ConfigReadyForUse` at `GenericPlatformCrashContext.cpp:247`. That delegate is broadcast only from `FConfigCacheIni::InitializeConfigSystem()` (`Engine\Source\Runtime\Core\Private\Misc\ConfigCacheIni.cpp:3837` and `:3930`; function begins `:3824`), and the only call site is `LaunchEngineLoop.cpp:5373`.

Therefore **the 2026-10-08 process executed `LaunchEngineLoop.cpp:5373`, which is strictly after `SetupOutputDevices()` at `:5354`.**

The `Engine.ini` write corroborates it: its content is exactly `[Core.System] Paths=...` followed by `[WindowsApplication.Accessibility] StickyKeysHotkey=False / ToggleKeysHotkey=False / FilterKeysHotkey=False / ...`, which is the output of `GConfig->SetBool("WindowsApplication.Accessibility", ...)` ×6 followed by `GConfig->Flush(false, GEngineIni)` at `Engine\Source\Runtime\ApplicationCore\Private\Windows\WindowsApplication.cpp:204-211`.

Since ports 2000/2001 were bound by that same PID (netstat-confirmed), init had also passed `FCarlaEngine::NotifyInitGame` — i.e. it was already deep into world/game-mode creation. The "burning CPU before log init" reading is internally contradictory.

### A.4 What `netstat LISTENING` proves, and what it does not

Start chain:

| Stage | Citation |
| --- | --- |
| `UCarlaGameInstance::NotifyInitGame` | `...\Plugins\Carla\Source\Carla\Game\CarlaGameInstance.h:62-65` |
| `ACarlaGameModeBase::InitGame` | `...\Game\CarlaGameModeBase.cpp:151` |
| `FCarlaEngine::NotifyInitGame` | `...\Game\CarlaEngine.cpp:77` |
| `Server.Start(RPCPort, StreamingPort, SecondaryPort)` | `CarlaEngine.cpp:87` |
| `FCarlaServer::Start` → `FPimpl` ctor, then logs `Initialized CarlaServer: Ports(...)` | `...\Server\CarlaServer.cpp:3318-3332` (log at `:3324-3330`) |
| rpclib `impl` ctor: `acceptor_(io_, tcp::endpoint(tcp::v4(), port))` — **bind + listen** | `G:\CARLA\carla_source_probe\Build\rpclib-src\lib\rpc\server.cc:33-38` |
| `pimpl->start_accept()` posts `acceptor_.async_accept(...)` | `server.cc:40-59`, invoked from `server::server` at `:104` |
| `Server.AsyncRun(...)` | `CarlaEngine.cpp:88` |
| `FCarlaServer::AsyncRun` → `Pimpl->Server.AsyncRun(RPCThreads)` | `CarlaServer.cpp:3347-3377`, call at `:3374` |
| rpclib `server::async_run(n)` → `loop_workers_.create_threads(n, ...)` running `pimpl->io_.run()` | `server.cc:138-145` |

**Key point:** `bind()`/`listen()` happen in the acceptor constructor; `accept()` only ever executes inside `io_.run()`. A TCP connect to a listening socket completes from the kernel accept backlog with **no user-space thread running at all**. So:

> LISTENING on 2000/2001 + successful connect + no reply within 60 s ⟺ either `async_run` was never reached, or `io_.run()` never executes. It does **not** by itself establish a "protocol handshake layer" defect.

Thread-count arithmetic rules out "async_run started zero threads":

- `FCarlaEngine_GetNumberOfThreadsForRPCServer()` = `max(hardware_concurrency, 4) - 2` ≥ 2 (`CarlaEngine.cpp:42-45`)
- `ThreadsPerServer = max(2, n/3)`, `RPCThreads = ThreadsPerServer` unless `-RPCThreads=` is given (`CarlaServer.cpp:3351`, `:3358-3361`); `-RPCThreads=` was not on the command line.

Also: **`-carla-server` is a no-op.** A search for `carla-server` over `*.cpp`, `*.h`, `*.cs`, `*.py` across the whole `G:\CARLA\carla_source_probe` tree returns zero hits (the only occurrence in the repo is the doc anchor `Docs\start_quickstart.md:11`). The listener starts unconditionally from `NotifyInitGame`.

### A.5 Ranked candidates for "binds, never answers"

The original ranking (pre-log blocking / busy loop) is withdrawn — the premise is falsified. Re-ranked against the actual evidence:

| # | Candidate | File:line | Status |
| --- | --- | --- | --- |
| 1 | rpclib io threads never scheduled, i.e. `FCarlaEngine.cpp:88` / `CarlaServer.cpp:3374` not reached or `io_.run()` never executes | `CarlaEngine.cpp:87`→`:88`; `CarlaServer.cpp:3347-3377`; `server.cc:138-145` | **UNKNOWN — highest-value.** rpclib names these threads `"server"` (`server.cc:140 name_thread("server")`), so a thread list is decisive |
| 2 | Connection never `accept()`ed — backlog only, so the client's request bytes are never read | `server.cc:40-59` | UNKNOWN — discriminator: state of the accepted socket on 2000 (`Listen` vs `Established`) |
| 3 | Sync-call path deadlocked pending game tick: `WrapSyncCall` posts to `_sync_io_context` then blocks on `result.get()`; that context is only pumped by `FCarlaServer::RunSome`/`SyncRunFor` from `FCarlaEngine::OnPreTick` | `LibCarla\source\carla\rpc\Server.h:109-122` (block at `:121-122`); `CarlaServer.cpp:3379-3383`; `CarlaEngine.cpp:297-311` | Does **not** explain `get_server_version` (see below) but deadlocks every `BIND_SYNC` handler |
| 4 | Game-thread busy loop in synchronous mode: `do { Server.RunSome(1u); } while (bSynchronousMode && !Server.TickCueReceived());` | `CarlaEngine.cpp:297-301` | Inactive by default (`bSynchronousMode` initialised from settings at `CarlaEngine.cpp:388`; `UCarlaSettings` sync mode off; no `Config\CarlaSettings.ini` in the project) |
| 4b | **Unconditional game-thread spin on the secondary-server path**: `do { Server.RunSome(1u); } while (!FramesToProcess.size());` — no sleep, spins until a `SEND_FRAME` command arrives | `CarlaEngine.cpp:306-310`; entered when `bIsPrimaryServer == false` (`:285`, `:303`) | **Excluded by configuration, re-verify on host.** `bIsPrimaryServer` is flipped only when `Settings.PrimaryIP` is non-empty (`CarlaEngine.cpp:105-108`; `CarlaSettings.h:92 std::string PrimaryIP = ""`); nothing under the project `Config\` tree or `E:\CARLA\CARLA_0.9.16` sets `PrimaryIP` (`CarlaSettings.cpp:78-79` reads `[CarlaServer] PrimaryIP`, `:143` a command-line override, neither present). Secondary mode also forces `bSynchronousMode = true` at `CarlaEngine.cpp:208` |
| 5 | Client/server protocol-handshake mismatch | — | **Untestable** until #1 and #2 are excluded |

Candidate #3 is explicitly excluded for this specific call: the Python client's `get_server_version` maps to `CallAndWait<std::string>("version")` (`LibCarla\source\carla\client\detail\Client.cpp:143-144`), and the server binds it with `BIND_ASYNC(version) << []() -> R<std::string> { return carla::version(); }` (`CarlaServer.cpp:270-272`). That dispatches on rpclib worker threads and never touches `_sync_io_context`.

### A.6 Instrumentation required for the next GAP-017 attempt

All cheap, none require a CARLA server restart loop beyond one launch each.

1. **Thread census with names** at 60 s: `cdb -p <pid> -c "~*n;k;q"` (or a `procdump` + `!threads`). Presence of a thread literally named `server` proves `server::async_run` ran (`server.cc:140`); absence proves candidate #1.
2. **Socket state**, not just LISTENING: `Get-NetTCPConnection -LocalPort 2000,2001,2002 | Select LocalAddress,LocalPort,State,OwningProcess`. `Established` on 2000 proves an `accept()` ran → candidate #2 excluded. Port **2002** (secondary, `CarlaSettings.h:89 SecondaryPort = 2002u`, alongside `RPCPort = 2000u` at `:83` and `StreamingPort = 2001u` at `:86`; constructed in `carla::multigpu::Router::Router(uint16_t port)` → `Listener` bind at `LibCarla\source\carla\multigpu\router.cpp:29-33`) is a second bind checkpoint.
3. **Turn logging on** so the divergence point becomes observable: rebuild with `bUseLoggingInShipping=true` (or use a Development/Test binary, or add `-abslog=` and verify the file appears). Then these two lines pin the split exactly:
   - `CarlaServer.cpp:3324-3330` → `Initialized CarlaServer: Ports(rpc=…, streaming=…, secondary=…)` (proves `FPimpl` bound)
   - `CarlaServer.cpp:3356` and `:3371-3372` → `FCommandLine …` and `FCarlaServer AsyncRun %d, RPCThreads %d, StreamingThreads %d, SecondaryThreads %d` (proves worker threads were requested)
4. **Stack capture at the 60 s timeout**: `procdump -ma -n 1 <pid>`. The register's own recommendation ("debugger attach or ETW trace rather than another plain launch-and-wait") is adopted as-is; items 1–3 make it conclusive.

**Status: GAP-017 remains `blocked_external`. No PASS claimed. No RPC test was executed in this diagnostic pass.**

---

## Part B — package-2975 cook stall (2026-10-05)

### B.1 Question as posed

Classify the stall that froze at `Cooked packages 2975 Packages Remain 583 Total 3558`; identify package 2975; determine whether every attempt dies on the same package; state whether existing evidence is sufficient or more forensics are required.

### B.2 Session inventory — four sessions, not three

`COOK_STALL_BATCH16.json` lists three. A fourth exists and is not recorded anywhere.

| Log (UTC name) | Local window | Lines | Mode | Final counter | Terminal evidence |
| --- | --- | --- | --- | --- | --- |
| `ingolstadt_cook_20261004T182534Z.log` | 10-04 20:25:34 → 10-05 11:17:59 (~14 h 52 m) | 8007 | cold | 2942 / Remain 616 / Total 3558 | **Fatal** — `ShaderCompiler.cpp:1236 Shader Compiling thread exception` + `GenericPlatformMemory.cpp:197 Ran out of memory allocating 1073741856 bytes` (exactly 1 GiB) |
| `ingolstadt_cook_20261005T092342Z.log` | 10-05 11:23:42 → 12:08:58 | 4510 | cold | 2921 / Remain 637 / Total 3558 | **Fatal** — `LogShaderCompilers: Error: Could not write the shader compiler transfer filename to 'C:/Users/admin/AppData/Local/Temp/UnrealShaderWorkingDir/…'` → `ShaderCompiler.cpp:1236` → `Assertion failed: ShaderCode.Num() [ShaderCore.h:553]` |
| `ingolstadt_cook_20261005T102819Z.log` | 10-05 12:28:19 → 12:37:32 (9 m 13 s) | 483 | warm (`-iterate`) | 1750 / Remain 1808 / Total 3558 | **Silent** — no fatal, no assertion, no OOM, no disk message; log ends immediately after a progress line |
| `ingolstadt_cook_20261005T105458Z.log` | 10-05 12:54:58 → 14:23:13 | 679 | warm (`-iterate`) | **2975** / Remain 583 / Total 3558 | **HANG** — see B.3 |

All four sessions report `Total 3558` on their final progress line, and in each `cooked + remain = 3558` (2942+616, 2921+637, 1750+1808, 2975+583), so the total is a stable per-run constant and the four numbers are directly comparable.

### B.3 Classification of session 4 — hang, not crash / OOM / disk-full

1. **No terminal error.** Counting `Fatal error|Assertion failed|Ran out of memory|Free Disk Space|Could not write the shader` over the 679-line capture returns **0**.
2. **The cook tick loop stayed alive.** Progress line 666 is the first `Cooked packages 2975`; lines 666–679 contain **12 identical heartbeats** interleaved with **2** `Cook Diagnostics` lines, both reading `OpenFileHandles=3559, VirtualMemory=6793MiB` (the preceding diagnostic at line 664 read 3560 / 6822 MiB, so both moved once and then froze). Heartbeats are emitted every `GCookProgressRepeatTime = 5.0f` seconds and diagnostics every `GCookProgressDiagnosticTime = 30.0f` seconds (`Engine\Source\Editor\UnrealEd\Private\CookOnTheFlyServer.cpp:135-151`), and only while `CookPendingCount != 0` (`:1226-1228`). The ~60 s span covered by 12 heartbeats + 2 diagnostics proves `UCookOnTheFlyServer::UpdateDisplay` kept being called (`:1220-1254`).
3. **583 packages were stuck in-progress.** `CookPendingCount = ExternalRequests->GetNumRequests() + PackageDatas->GetMonitor().GetNumInProgress()` (`CookOnTheFlyServer.cpp:1225`); `FPackageDataMonitor::GetNumInProgress()` returns `NumInProgress` maintained by `OnInProgressChanged` (`Engine\Source\Editor\UnrealEd\Private\Cooker\CookPackageData.cpp:1000-1014`). That count did not move for the entire frozen window — nothing completed and nothing was added.
4. **The shader pipeline stopped, not the cooker.** There are **73** `LogShaderCompilers` lines in the whole capture; the last is line **662**: `Worker (2/4): shaders left to compile 15034`. No `LogShaderCompilers` line appears after it, and there is **no** `ShaderCompileWorker crashed`, `ShaderCompileWorker terminated unexpectedly` (`ShaderCompiler.cpp:1472`), or `Couldn't launch … ShaderCompileWorker` (`:2342`, `:2349`) anywhere. Queue depth had already spiked repeatedly during this session (11 900, 15 034, 8 668, 8 658, …) while all four slots reported work.
5. **Retry storm in the tail (symptom, not cause).** 289 × `LogMaterial: Display: Missing cached shader map for material …, compiling.` — of which `M_DHair_MASTER` 50 and `M_Fabric_Master` 40 — plus 38 × `ShadingModel MSM_Hair not supported in feature level ES3_1` and 38 × `Failed to compile Material Instance … Default Material will be used in game`, all against `MI_DHair_MASTER_Inst_v6celles.uasset`.
6. **Disk output stopped before the log did.** Last `.uasset` write: **14:22:08** local; log last write: **14:23:13** — ≈65 s of continued ticking with zero new output. Owner terminated the session (per `COOK_STALL_BATCH16.json`, disposition `killed by owning session … to pivot to uncooked serving`).
7. **External telemetry agrees the process was idle.** `COOK_RESOURCE_TIMELINE.csv` (4 samples, 14:53–15:27 local): `UE4_CPU_sec` 1323.6 → 1347.7 (+24.1 CPU-seconds over 34 min ⇒ ~0 busy cores), `SCW_Count` **0 on every sample**, working set 2238 → 216 MB, `C_Free` 19.42 → 15.61 GB (≈4 GB written to C: while UE4 was idle — unexplained and worth re-measuring), `G_Free` flat at 41.69 GB.

**Verdict: a hang / resource starvation in the shader-compilation pipeline, with the cooker left ticking and waiting. Not a crash, not an OOM, not disk-full.**

### B.4 What package 2975 is — not determinable from existing evidence

- The stdout capture contains **no package names at all** (no `LogSavePackage`, `Saved package`, or `BeginSave` lines in 679 lines).
- `G:\CARLA\cook_out\Ingolstadt` contains exactly **2973 `.uasset` files** (7148 files counting `.uasset`/`.uexp`/`.ubulk`) versus the reported counter value **2975** — a delta of 2 that is not explained by any surviving artefact.
- There are **zero `.umap` files** in the output. The requested map `/Game/Ingolstadt/Maps/Ingolstadt/Ingolstadt` was never cooked, which matches `COOKED_MAP_AUTHORITY` (`map_package_cooked: false`, `cook_output_files: []`, `streaming_tile_packages_present: 0`, `cook_stalled_at_package: 2975`, `total_packages_discovered: 3558`). Package 2975 is therefore **not** the target map — it is dependency content, 583 packages short of completion.
- **All 2973 `.uasset` were written inside session 4's window** (12:54:00–14:24:00 local); **zero** `.uasset` exist outside it. Counting all `.uasset`/`.uexp`/`.ubulk` per session window gives 0 (session 1), 15 (session 2, no `.uasset`), 1 (session 3, no `.uasset`) and 7132 including all 2973 `.uasset` (session 4). Sessions 1–3 therefore produced no usable `cook_out` output.
- The final writes cluster at `14:22:07`–`14:22:08`. The 12 `.uasset` written in the last second are:

  `CarlaUE4\Content\Carla\Blueprints\Game\CarlaGameMode` · `Blueprints\Weather\BP_Weather` · `Blueprints\Walkers\WalkerFactory` · `Blueprints\Walkers\BP_Walker_MaleEuro` · `Blueprints\Walkers\BP_Walker_MaleEuro_v2` · `Static\Particles\rain\PS_Rain` · `Static\Pedestrian\Materials\MH_microdetail\Fabric_30_R` · `Static\Pedestrian\AsiaM_\Textures\T_Skin\T_AsianMaleSkinMH_d` · `…\T_AsianMaleSkinMH_n` · `Static\Pedestrian\AsiaM_\Textures\T_Military_model\T_AdClothN04_d` · `…\T_AdClothN04_n` · `…\T_AdClothN04_MMAp`

- **Bounded but unnamed:** package #2975 is in that final-second pedestrian/walker/weather cluster, or is one of the ≤2 packages the counter credited but that never hit disk. Cook order cannot be reconstructed from mtime — 12 packages share the same 1-second timestamp, and NTFS does not record finer ordering. Naming it requires a re-run (B.8 item 2).

### B.5 Is it the same package every attempt? — No

Only **one** session ever reached 2975. The two fatal sessions died **33 and 54 packages short** of it (2942, 2921); the silent session died at 1750. On the available data 2975 is a **high-water mark, not a demonstrated poison package**. A poisoned-package hypothesis is not supported and would be an over-claim.

Note also that sessions 3 and 4 were warm `-iterate` runs (`LogCook: Display: Iterative cooking summary for WindowsNoEditor` appears **only** in those two logs) while 1 and 2 were cold, so their workloads were not comparable even before the counter values are considered.

### B.6 Contributing factors that *are* evidence-backed

1. **`PCD3D_ES31` is an unnecessary third shader platform.** `SHADER_PLATFORM_SCOPE_AUDIT.json`: expected `[PCD3D_SM5, SF_VULKAN_SM5]`, actual `[PCD3D_SM5, SF_VULKAN_SM5, PCD3D_ES31]`, sourced from `DefaultEngine.ini:[/Script/WindowsTargetPlatform.WindowsTargetSettings] +TargetedRHIs=PCD3D_ES31 (line 109)`. In session 4, **49 of the 50** `for platform …` mentions are `PCD3D_ES31` (the 50th is the unrelated `Sandbox cleanup … for platforms WindowsNoEditor` at log line 117), and all 38 `MSM_Hair not supported in feature level ES3_1` failures are ES3.1-only.

   **Line-109 status, re-verified this pass:** the `+TargetedRHIs=PCD3D_ES31` line is **no longer present** in the source config — `G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Config\DefaultEngine.ini` line 109 is now `DefaultGraphicsRHI=DefaultGraphicsRHI_DX12`, and a search of every `*.ini` under the project and under `G:\UnrealEngine_4.26_CARLA\Engine\Config` returns **zero** `PCD3D_ES31` hits. That file's mtime is **2026-10-05 17:15:36**, i.e. **after** session 4 stopped at 14:23:13 the same day, so the edit is consistent with having been made post-stall. The audit's "line 109" citation is corroborated by the packaged copy, which still carries it verbatim: `E:\CARLA\CARLA_0.9.16\CarlaUE4\Config\DefaultEngine.ini:109: +TargetedRHIs=PCD3D_ES31` (that file mtime 2026-05-01 17:07:42). Conclusion: the **config-only, source-stage fix appears already applied**; what remains is to confirm it takes effect (B.8 item 6) and to reconcile the stale packaged copy. No map, XODR or cooked-artifact mutation is involved either way.
2. **Memory policy is half-configured.** `COOK_MEMORY_POLICY_AUDIT.json`, from session 4 log line 107 (`LogCook: Display: CookSettings for Memory: …`): `MemoryMaxUsedPhysical 16384MiB`, `MemoryMinFreePhysical 1024MiB`, `MemoryMaxUsedVirtual 0MiB` (unlimited), `MemoryMinFreeVirtual 0MiB`. ShaderCompileWorker processes are separate and excluded from cooker accounting.
3. **DDC is degraded but was not the proximate stall signal.** `DDC_PERFORMANCE_AUDIT.json`: `G:\UnrealEngine_4.26_CARLA\Engine\DerivedDataCache` 9.27 GB / 82 834 files, runtime read 0.00–0.08 MB/s, drive G: at 4.5 % free. Flagged `DDC_PERFORMANCE_BLOCKER: true`, but session 4 shows no DDC error or stall line.
4. **Scope is genuinely large.** `COOK_FLAG_SEMANTICS_AUDIT.json`: `-cooksinglepackage` does **not** limit scope in UE4.26 — full transitive dependency discovery runs; final total 3558.
5. **Temp-dir remediation held.** The C: `UnrealShaderWorkingDir` write failure appears only in session 2; sessions 3–4 show no such line, consistent with the `TEMP`/`TMP` redirect to `G:\CARLA\cook_temp`.

### B.7 Claims that are **not** established (explicit gaps)

1. **Package identity (B.4)** — insufficient evidence.
2. **"System commit saturated 59 506 256 / 59 506 256" — treat as unverified.** In `COOK_RESOURCE_TIMELINE.csv` `Sys_Commit_MB` equals `Sys_CommitLimit_MB` on **every** sample, and `PAGEFILE_CAPACITY_AUDIT.json` reports physical RAM 50 069 MB + pagefile 9 437 MB = 59 506 MB — i.e. the recorded *value* equals the *theoretical limit*, which is the signature of reading one counter twice. The same rows report `Sys_Avail_RAM_GB = 21.08`, which is hard to square with true saturation. Re-measure with separate `\Memory\Committed Bytes` and `\Memory\Commit Limit` counters before quoting this as root cause.
3. **"Zero live ShaderCompileWorkers ⇒ the workers died/were killed" — not established.** `SCW_Count = 0` is a process census; `SCW_AGGREGATE_PEAK_GB = NOT_MEASURED`. There is no spawn/exit logging (`LogShaderCompilers` at Verbose was never enabled), no process-event log, no thread dump. The absence of `Couldn't launch`/`terminated unexpectedly` lines in the capture is **weak** — the whole capture has only 73 shader-compiler lines.
4. **Receipt timestamps are local time mislabeled `Z`.** `CURRENT_COOK_FINAL_RECEIPT.json` `start_time 2026-10-05T12:54:59Z` contradicts its own log filename `…T105458Z` and the file's creation time 12:54:58 local; `LIVE_COOK_FINAL_STATE.json` `observed_at_utc 2026-10-05T09:20:00Z` sits *before* its own `log_final_last_write_local 2026-10-05 11:17:59`. Both are UTC+02:00 local values wearing a `Z`.
5. **Provenance gap in the receipt.** `CURRENT_COOK_FINAL_RECEIPT.json` cites `G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Saved\Logs\CarlaUE4.log` as evidence; that file is now 960 223 B dated **2026-10-07 23:31:29** (rotated by later sessions), and `Saved\Logs\CarlaUE4-backup-*.log` files exist only from 10-07. The only surviving full record of session 4 is `G:\CARLA\build_logs\ingolstadt_cook_20261005T105458Z.log` (78 131 B, 679 lines).
6. **No UAT logs exist.** Neither `G:\UnrealEngine_4.26_CARLA\Engine\Programs\AutomationTool\Saved` nor `…\AutomationTool\Logs` exists on this host; the cook was launched directly as `UE4Editor.exe … -run=cook` (command line recorded in `COOK_FLAG_SEMANTICS_AUDIT.json`).
7. **Stale citations in `COOK_PACKAGE_EXPANSION_AUDIT.json`.** Its line references (667, 699, 789-790, 876) match no surviving log — session 4 has 679 lines, and session 1 (8007 lines) has a `LogTexture` line at 667. Its quoted totals (1754, 1778, 3553) also differ from the `Total 3558` printed in the final line of all three terminated sessions. Treat that file's line numbers as unusable; its qualitative point (`-cooksinglepackage` does not restrict scope) stands independently in `COOK_FLAG_SEMANTICS_AUDIT.json`.

### B.8 Instrumentation required for the next cook attempt

1. **Unique, explicit log path.** Add `-abslog=G:\CARLA\build_logs\<run>.ue4log` and keep `-stdout`; record SHA-256 + byte length at exit. This removes dependence on `Saved/Logs` rotation (see B.7 item 5).
2. **Package identity without engine verbosity.** Poll `G:\CARLA\cook_out\Ingolstadt` every 5 s into a CSV (`LastWriteTime`, `FullName`); the package that stops being written when `Cooked packages N` freezes is then directly readable, and the `.uasset` count cross-checks the counter. Separately, raise `LogCook` verbosity (`-LogCmds="LogCook Verbose"`) **only after** a one-package smoke cook confirms it actually prints package names — do not assume it does.
3. **Shader-pipeline visibility.** `-LogCmds="LogShaderCompilers Verbose"` to surface `LaunchWorkersIfNeeded` (`ShaderCompiler.cpp:1420`), `Couldn't launch %s!` (`:2342`, `:2349`) and `ShaderCompileWorker terminated unexpectedly` (`:1472`); also record the computed `NumShaderCompilingThreads` (`:2055-2116`) and the `Only %d SCWs will be spawned` warning path (`:1154-1156`).
4. **Corrected census, every 15 s.** Name / PID / PPID / working set / private bytes / CPU seconds / commit for `UE4Editor*` **and** `ShaderCompileWorker*`; separate `Get-Counter '\Memory\Committed Bytes'` and `'\Memory\Commit Limit'` (replaces the double-read commit column that produced B.7 item 2); free space on C:, G:, F:; and the cook PID's **own** `%TEMP%` (`GetTempPath()` of that process, since `TEMP`/`TMP` were redirected to `G:\CARLA\cook_temp` — verify in-process, not from the parent shell).
5. **Watchdog + dump — the single highest-value missing artefact.** If `Cooked packages N` is unchanged for ≥10 min: `procdump -ma -n 1 <cookpid>` **and** a dump of any live `ShaderCompileWorker`, then stop the run. A dump resolves whether the game thread is blocked on a shader-map wait, on DDC, or in save-package I/O.
6. **Confirm the RHI-scope fix, do not re-apply it blindly.** The `+TargetedRHIs=PCD3D_ES31` line has **already been removed** from `G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Config\DefaultEngine.ini` (mtime 2026-10-05 17:15:36; see B.6 item 1) — the next cook must therefore start by asserting `grep PCD3D_ES31 <project>\Config\*.ini` is empty, then verify from the run that no `for platform PCD3D_ES31` and no `MSM_Hair not supported in feature level ES3_1` lines appear and that `ACTUAL_SHADER_PLATFORMS == [PCD3D_SM5, SF_VULKAN_SM5]` per `SHADER_PLATFORM_SCOPE_AUDIT.json`. If ES31 reappears, the source is *not* the project ini (none contains it) — record the effective `[/Script/WindowsTargetPlatform.WindowsTargetSettings]` section from `Saved\Config\Windows\Engine.ini` and the cook command line before concluding. Reconcile the stale packaged copy `E:\CARLA\CARLA_0.9.16\CarlaUE4\Config\DefaultEngine.ini:109`, which still declares the line.
7. **Antivirus visibility.** GAP-018 records a live Avast IDP.Generic quarantine of `G:\UnrealEngine_4.26_CARLA\Engine\Binaries\Win64\UE4Editor.exe`, and `ShaderCompileWorker.exe` lives in the **same directory** (`ShaderCompiler.cpp:1956`). Record Avast quarantine and `autosandbox.log` activity for the cook window.
8. **Do not rely on `-TestExit=`** for a cook commandlet without first verifying it exits: `FOutputDeviceTestExit::Serialize` issues `CLOSE_SLATE_MAINFRAME` when `GIsEditor` (`LaunchEngineLoop.cpp:397-436`, branch at `:414-427`), which may not terminate a commandlet. Prefer the external watchdog in item 5.

---

## What is not claimed

- No GAP-017 PASS. No RPC, port, `get_server_version` or stack test was executed in this pass. GAP-017 stays `blocked_external`.
- No cook receipt. `COOKED_MAP_AUTHORITY.cook_completed` remains `false`; no `cook_out` tree is complete (no `.umap`).
- Package 2975 is not named.
- Commit saturation and "dead shader workers" are recorded as **unverified**, not as root cause.
- `MASTER_GAP_REGISTER.json` was **not** edited. GAP-017's 2026-10-08 note and `COOK_STALL_BATCH16.json` remain as written; the corrections above are findings for a follow-up update by the register owner.
- No map promotion, no XODR mutation, no frozen-evidence rewrite.

## Artefacts read (this pass)

`MASTER_GAP_REGISTER.json` (GAP-017 entry) · `COOK_STALL_BATCH16.json` · `LIVE_COOK_FINAL_STATE.json` · `CURRENT_COOK_FINAL_RECEIPT.json` · `COOK_RESOURCE_TIMELINE.csv` · `PAGEFILE_CAPACITY_AUDIT.json` · `COOK_MEMORY_POLICY_AUDIT.json` · `SHADER_PLATFORM_SCOPE_AUDIT.json` · `DDC_PERFORMANCE_AUDIT.json` · `COOK_FLAG_SEMANTICS_AUDIT.json` · `COOK_PACKAGE_EXPANSION_AUDIT.json` · `COOK_FORENSICS_FINAL_OUTPUT.txt` · `COOK_CONFIGURATION_CLOSURE_FINAL.txt` · `SHADER_QUEUE_GROWTH_ANALYSIS.json` · `G:\CARLA\build_logs\ingolstadt_cook_20261004T182534Z.log` · `…20261005T092342Z.log` · `…20261005T102819Z.log` · `…20261005T105458Z.log` · `G:\CARLA\build_logs\active_cook_cmd.txt` · `G:\CARLA\cook_out\Ingolstadt` (metadata only) · `C:\Users\admin\AppData\Local\CarlaUE4\Saved\**` (metadata only) · `E:\CARLA\CARLA_0.9.16\**` (metadata only)

Engine/CARLA source cited above was opened read-only.
