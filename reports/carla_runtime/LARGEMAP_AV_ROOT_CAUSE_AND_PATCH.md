# ALargeMapManager Access Violation — Root Cause Investigation and Patch Proposal

- Deliverable: `LARGEMAP_AV_ROOT_CAUSE_AND_PATCH.md`
- Verdict: **LARGEMAP_CAUSE_HYPOTHESIS_WITH_EVIDENCE**
- Date: 2026-10-21/22
- Scope: offline source-grounded analysis only. **No CARLA installation was modified. No patch was compiled. No fix is claimed as applied.**

## 1. Exact binary identity (verified this session)

| Artifact | Path | Size | SHA-256 | Status |
|---|---|---|---|---|
| Launcher | `E:\CARLA\CARLA_0.9.16\CarlaUE4.exe` | 191,488 B | `0bc4b3d089470ffdc91a2ec6bf2f26187de271d0e9e71a01beee8416633c7320` | Verified; matches `CARLA_RUNTIME_RECEIPT.json` (2026-10-02) |
| Shipping binary | `E:\CARLA\CARLA_0.9.16\CarlaUE4\Binaries\Win64\CarlaUE4-Win64-Shipping.exe` | 91,477,504 B | not recomputed this session (838 MB PDB present alongside) | Verified present |
| Symbols | `E:\CARLA\CARLA_0.9.16\CarlaUE4\Binaries\Win64\CarlaUE4-Win64-Shipping.pdb` | 838,332,416 B | — | Present → symbol resolution possible in principle |

The launcher SHA is byte-identical to the previously qualified runtime receipt, so the running binary is the same one that previously produced `RUNTIME_READY` (2026-10-02, `CARLA_RUNTIME_RECEIPT.json`). The crash being investigated is therefore observed against a binary whose identity is pinned.

## 2. Source availability — what was and was not found

Required source path (per task): `Unreal/CarlaUE4/Plugins/Carla/Source/Carla/MapGen/LargeMapManager.cpp`

Searched:
- `G:\UnrealEngine_4.26_CARLA\Plugins\Carla\Source\Carla\MapGen\LargeMapManager.cpp` → **not present**
- `G:\UnrealEngine_4.26_CARLA\Engine\Plugins\Carla\Source\Carla\MapGen\LargeMapManager.cpp` → **not present**
- `G:\UnrealEngine_4.26_CARLA` exists (`UE4_ROOT` env var) → **binary/engine tree present, CARLA plugin C++ source not vendored**
- Repository `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main` (branch `integration/carla-final-convergence-20261014`, HEAD `69c818be`) → **no `LargeMapManager.cpp`** (recursive filename search, zero hits)
- `E:\CARLA\CARLA_0.9.16\CarlaUE4\` → packaged build; `.cpp` sources not shipped

**Consequence:** the published public CARLA source snippet supplied in the assignment is the only available source text. It is *not* proven byte-identical to the code compiled into `CarlaUE4-Win64-Shipping.exe`. This is stated explicitly as an open provenance gap (see §7).

## 3. Source logic under analysis (as supplied in the assignment)

```cpp
void ALargeMapManager::OnLevelRemovedFromWorld(ULevel* InLevel, UWorld* InWorld)
{
    FCarlaMapTile& Tile = GetCarlaMapTile(InLevel);
    Tile.TilesSpawned = false;
}
```

`GetCarlaMapTile(ULevel* InLevel)` searches registered tiles by streaming-level identity and **assumes a matching tile exists**. If no tile matches, the lookup yields an invalid (null/dangling) reference, and `Tile.TilesSpawned = false;` writes through it.

### 3.1 The faulting write
- Offset `+0x9` into `OnLevelRemovedFromWorld` is consistent with a member store into the returned tile reference (the `TilesSpawned` bool write) — the reference is resolved, then dereferenced.
- Exception is `EXCEPTION_ACCESS_VIOLATION writing 0x28` → writing at address `0x28`, i.e. `base + 0x28` where `base == 0`. This is the signature of a **null reference dereference with a non-zero member offset** (`TilesSpawned` at struct offset `0x28`, or a null `FCarlaMapTile*` whose field sits at `0x28`).
- A null base of `0x00` with a `0x28` member offset is the classic fingerprint of `GetCarlaMapTile()` returning a null/empty reference rather than an out-of-range array index.

### 3.2 Why the callback can receive an unregistered level
`ALargeMapManager` registers itself for `FWorldDelegates::OnLevelRemovedFromWorld` (or equivalent streaming delegate). Legitimate sequences that remove a level **without** a matching registered tile:

1. **World teardown**: on `UWorld::CleanupWorld` / map travel, levels are removed while `MapTiles` may already have been cleared, or before tiles are registered for the *next* world.
2. **Streaming level unload of a tile that was never registered as a tile** (e.g. a level streamed by a different subsystem — minimap/annotation levels, `ULevel` instances created for the tile parent vs. child).
3. **Double removal**: the same level removal event delivered twice (delegate re-registration, or removal during teardown after an explicit removal). The assignment explicitly asks whether the same event can occur twice — nothing in the published snippet is idempotent-safe: `GetCarlaMapTile` has no "already removed" short-circuit.
4. **Map transition (not initial startup)**: at startup the tile set is registered *after* the streaming levels are created; during a transition, the *old* world's levels are removed while the manager's tile array may already point at the *new* world's tiles or be mid-rebuild.

### 3.3 Destruction-order invalidation
`ALargeMapManager` owns `FCarlaMapTile` entries that reference `ULevel*` objects and own spawned actor sets. If the manager's own destruction or its `MapTiles` reset runs before the world's level-removal notifications are flushed, the callback runs against a container that is being torn down. That is the classic "destruction order invalidates MapTiles before callbacks finish" scenario named in the assignment, and it matches an AV that occurs at *shutdown/transition* rather than at steady-state streaming.

## 4. Runtime evidence collected this session (2026-10-21/22)

Bounded startup (`reports/carla_runtime/CARLA_BOUNDED_STARTUP_RESULTS.json`):
- `SERVER_PROCESS_ALIVE`: yes (PID 22152 shipping / 36076 launcher)
- `RPC_READY`: yes — `get_server_version()='0.9.16'`, 15 maps available
- `WORLD_TICKS_READY`: yes — snapshot frame 11 at handshake; frame 2383 after `load_world("Grid0828")`; frame 4231 → 4238 during sensor capture
- `RENDERING_READY`: yes — diagnostic RGB produced 1,228,800 B raw (640×480×4), pixel mean 155.50, std 18.57, max 244 → **non-empty rendered pixels**
- `SENSOR_READY`: yes for a single low-res RGB sensor (diagnostic only, not the frozen RQ3 rig)

**The `ALargeMapManager` access violation did NOT reproduce** in this session: Town10HD_Opt (streamed, tiled) loaded and streamed; Grid0828 loaded; no teardown crash was triggered because the server was terminated by an explicit `Stop-Process` (a hard kill that bypasses graceful world teardown) rather than through a map-travel/teardown sequence.

**This is the key experimental gap**: the crash is most likely on **graceful world teardown / map transition**, and this session deliberately used a hard kill for ownership safety. Reproducing it requires a *graceful* teardown (or an explicit `client.unload_world()` / second `load_world()`) while capturing a minidump.

## 5. Minidump status

- Searched: `C:\Users\admin\AppData\Local\CrashDumps` (contains only ChatGPT/codex/git/DuckDuckGo/Telegram/SnippingTool/FileCoAuth dumps — **no CARLA dump**), `C:\Windows\MinDumps` (absent), `E:\CARLA\CARLA_0.9.16` (no `.dmp`), `CarlaUE4\Saved\Logs` (no crash/shader logs), repo-wide `*.mdmp|*.dmp` search (none).
- The assignment states "three historical minidumps exist" — **they are not present in this workspace and are not in any repo worktree**. They may live on the damaged `H:` Phase 6 worktree (explicitly out of bounds: "Do not touch Codex's damaged H: Phase 6 worktree") or on an offline archive.
- **Therefore the exact faulting instruction pointer was NOT disassembled.** Instruction-level attribution is based on the exception signature (`writing 0x28`), the reported `+0x9` offset, and the published source semantics — not on a recovered disassembly. This is the principal reason the verdict is *hypothesis with evidence* and not *confirmed*.

## 6. Proposed remediation (OFFLINE PROPOSAL ONLY — NOT APPLIED)

Target file (in a source checkout that vendors the plugin):
`Plugins/Carla/Source/Carla/MapGen/LargeMapManager.cpp`

### 6.1 Design constraints honoured
- Assertions are **not** simply removed; ownership invariants are kept and made explicit.
- The callback is **not** suppressed indiscriminately — only the specific "level removed that has no registered tile" case is handled, and it is logged.
- The returned tile reference is **never dereferenced when invalid**.
- The fix targets the *lookup*, not the symptom.

### 6.2 Minimal patch proposal (illustrative; final form must be compiled against the real source)

```cpp
// LargeMapManager.h  (proposed)
UFUNCTION(BlueprintCallable, Category = "Large Map")
bool TryGetCarlaMapTile(ULevel* InLevel, FCarlaMapTile*& OutTile) const;   // returns false when unregistered
```

```cpp
// LargeMapManager.cpp  (proposed)
bool ALargeMapManager::TryGetCarlaMapTile(ULevel* InLevel, FCarlaMapTile*& OutTile) const
{
    OutTile = nullptr;
    if (InLevel == nullptr)
    {
        return false;
    }
    for (FCarlaMapTile& Tile : MapTiles)
    {
        if (Tile.StreamingLevel == InLevel)   // exact streaming-level identity match
        {
            OutTile = &Tile;
            return true;
        }
    }
    return false;                              // unregistered level — caller decides
}

void ALargeMapManager::OnLevelRemovedFromWorld(ULevel* InLevel, UWorld* InWorld)
{
    FCarlaMapTile* Tile = nullptr;
    if (!TryGetCarlaMapTile(InLevel, Tile))
    {
        // Legitimate during world teardown / map transition / non-tile streaming level.
        // Log and ignore: no ownership invariant is violated, there is simply no tile
        // to reset. Assertion is intentionally NOT used here (teardown ordering differs
        // between editor, cook and shipping).
        UE_LOG(LogCarla, Verbose, TEXT("OnLevelRemovedFromWorld: level %p has no registered tile (teardown/transition); ignoring"),
               InLevel);
        return;
    }
    Tile->TilesSpawned = false;
}
```

Optional hardening (must be evaluated against the real source, not applied blind):
- Guard `MapTiles` mutation against re-entrancy from the same delegate (`bHandlingLevelRemoval`).
- Make the removal path idempotent (a second removal of the same level must be a no-op, not a lookup of an already-cleared tile).
- Ensure the manager's `BeginDestroy`/teardown unsubscribes the world delegate **before** `MapTiles` is emptied.

### 6.3 Negative tests required before any promotion
| Test | Expected |
|---|---|
| Remove a level that has no registered tile | no crash; one verbose log line; server survives |
| Remove the same level twice | second call is a no-op; no crash |
| Remove a tile level during `unload_world()` | tile found → `TilesSpawned=false`; no crash |
| Remove a tile level during graceful `load_world()` transition (old world) | no crash |
| `MapTiles` emptied before delegate flush | no crash (callback sees empty container) |
| Null `InLevel` | no crash |
| Registered-tile removal still resets `TilesSpawned` | **must remain true** (no behavioural regression) |
| Full RQ3 streaming stress (tile seam crossing) | no crash; identical tile/actor bookkeeping |

### 6.4 Build-verification plan (not executed)
1. Obtain the CARLA 0.9.16-matching source revision (see §7) and confirm the file/function names match the proposal above (proposal is written against the *published* snippet; real names may differ, e.g. `MapTiles` container name).
2. Compile `Carla` module for Win64 Shipping against `G:\UnrealEngine_4.26_CARLA` (UE4.26 fork) with MSVC matching the original build.
3. Replace only `CarlaUE4-Win64-Shipping.exe` in a **copy** of `E:\CARLA\CARLA_0.9.16` (never in-place while protected), then re-run the negative tests above.
4. Compare the new binary SHA and record it as a **separate** runtime receipt; the current qualified binary (`0bc4b3d0…`) must remain the reference until the new one passes the full matrix.

**No build was attempted**: §7 storage admission is not met (see `CARLA_STORAGE_AND_NATIVE_BUILD_ADMISSION.md`).

## 7. Open provenance gaps (why the verdict is not "CONFIRMED")

1. **No matching source in the workspace.** The proposal is written against the published snippet; the exact member names, container name and the actual `GetCarlaMapTile` implementation in the shipped binary are unverified.
2. **No minidump recovered.** The three historical dumps named in the assignment are absent from this workstation's search paths; the H: worktree is out of bounds.
3. **No instruction-level disassembly.** Attribution rests on `EXCEPTION_ACCESS_VIOLATION writing 0x28` + `OnLevelRemovedFromWorld+0x9` + published semantics.
4. **Crash not reproduced.** The failing scenario (graceful teardown / map transition) was not exercised; the session used a hard kill.
5. **Binary/source correspondence unproven.** The instruction "do not assume the published source matches the packaged binary" is respected: the correspondence is asserted as an open gap, not closed.

## 8. Smallest next test to close the gap (bounded)

1. Start the server with the proven flags (`-RenderOffScreen -quality-level=Low -nosound`).
2. Enable crash capture: `-abslog`, `-crashreports` (UE4 crash reporter) and `HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps` for `CarlaUE4-Win64-Shipping.exe` (user-write, no driver change) to force a *minidump* on AV.
3. Trigger a **graceful** teardown: `client.unload_world()` or a second `load_world("Town10HD_Opt")` from `Grid0828`.
4. If the AV reproduces, recover the minidump and resolve the IP against the 838 MB PDB → confirm the faulting instruction is the `TilesSpawned` store and confirm `GetCarlaMapTile` returned null.
5. If it does **not** reproduce, the crash is not in the ordinary transition path and the hypothesis must be re-scoped (candidate: large-map import/streaming subsystem path rather than the level-removal callback).

## 9. Verdict

**LARGEMAP_CAUSE_HYPOTHESIS_WITH_EVIDENCE**

The published source semantics explain the exception signature exactly (null tile reference → write at `base+0x28`), the callback can legitimately receive an unregistered level during world teardown and map transitions, and the shipped binary is pinned by SHA-256. Promotion to `LARGEMAP_CAUSE_CONFIRMED` requires the minidump + PDB instruction attribution described in §8, which was not obtainable here (no dump on disk, source not vendored, teardown path not exercised).
