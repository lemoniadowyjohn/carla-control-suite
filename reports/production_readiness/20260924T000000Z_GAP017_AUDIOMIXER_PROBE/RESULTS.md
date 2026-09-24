# GAP-017 audio-mixer-disable probe (2026-09-24)

## New angle tried, and why

Prior attempts: (1) cdb stack capture during a live hang found the game
thread blocked in `FEventWin::Wait -> FAudioCommandFence::Wait ->
FAudioDeviceManager::UpdateActiveAudioDevices -> UGameEngine::Tick`; (2)
`-nosound` was tried and did not fix it -- port 2000 still listened,
`get_server_version()` still hard-timed-out. `-nosound` only mutes output
volume (`UnfocusedVolumeMultiplier`/similar); it does not change which
audio device module is loaded or whether the Audio Mixer subsystem
initializes and enumerates devices.

Checked the packaged config directly (not the in-progress UE4 source build
at `G:\UnrealEngine_4.26_CARLA` -- not touched, per boundaries):

* `E:\CARLA\CARLA_0.9.16\Engine\Config\Windows\WindowsEngine.ini` `[Audio]`:
  `AudioDeviceModuleName=XAudio2`, `AudioMixerModuleName=AudioMixerXAudio2`,
  `UseAudioMixer=true`.
* `E:\CARLA\CARLA_0.9.16\Engine\Config\BaseEngine.ini` `[Audio]`:
  `EnableAudioMixer=false` (generic default, overridden per-platform above).
* `CarlaUE4\Config\DefaultEngine.ini` has no `[Audio]` section override at
  all -- only `[/Script/WindowsTargetPlatform.WindowsTargetSettings]`
  cook-time audio encode settings (sample rate, buffer size), unrelated to
  which device module loads at runtime.
* The shipping binary is a monolithic single exe
  (`CarlaUE4\Binaries\Win64\CarlaUE4-Win64-Shipping.exe`, no separate
  per-module DLLs beside third-party Chrono/turbojpeg) -- confirmed no
  `NullAudio*.dll` is shipped, so a bare `AudioDeviceModuleName=NullAudio`
  override would risk loading a module that was never linked in.

New angle: use UE4's built-in `-ini:<File>:[Section]:Key=Value` command-line
override syntax (no file copy needed, nothing in the install touched) to
force `UseAudioMixer=False` and `EnableAudioMixer=False` and blank out
`AudioDeviceModuleName`, targeting the Audio Mixer subsystem initialization
path itself -- the actual code path that owns `FAudioDeviceManager::
UpdateActiveAudioDevices` -- rather than muting output as `-nosound` does.

Launch command used:
```
E:\CARLA\CARLA_0.9.16\CarlaUE4.exe -carla-server -nullrhi -carla-rpc-port=2000 \
  -windowed -ResX=640 -ResY=480 -nosound \
  -ini:Engine:[Audio]:UseAudioMixer=False \
  -ini:Engine:[Audio]:EnableAudioMixer=False \
  -ini:Engine:[Audio]:AudioDeviceModuleName=
```
(`-nosound` kept alongside as a harmless belt-and-braces since it was
already proven not to hurt; the new, load-bearing part is the three `-ini:`
overrides.) Full command line: `launch_cmdline.txt` in this directory.

## Launch result

* Launcher PID spawned the real shipping child (`CarlaUE4-Win64-Shipping.exe`,
  PID 31680 this run) -- same launcher/child PID-split behavior documented
  previously; harnesses must follow the process tree.
* Shipping process reached ~5.89 GB working set (matches the ~5.7-5.9GB
  "real initialization" threshold from both prior attempts).
* Port 2000 went LISTENING within ~25s of launch (`netstat`/
  `Get-NetTCPConnection`, owned by the shipping PID) -- consistent with
  prior attempts.
* `carla.Client(...).get_server_version()` was attempted twice: once with a
  30s timeout, once with a 60s timeout. **Both hard-timed-out** with the
  process still alive and the port still listening throughout
  (`RuntimeError: time-out of Nms while waiting for the simulator`).

**This does NOT resolve GAP-017.** The RPC handshake still never completes.

## Is it the same hang, or something different?

Something different, and narrower. Two `cdb.exe -p <pid> -c "~*kb; qd"` /
`"~0kb; qd"` non-invasive snapshots were taken (attach, dump stacks, detach
without killing -- `qd`, not `q`):

* `cdb_all_threads_t0.txt` -- taken ~55s after launch, right after the
  first 30s client timeout. All 54 threads dumped. **No frame anywhere in
  the entire dump references `FAudioDeviceManager`, `FAudioCommandFence`,
  or any audio-mixer-specific thread name** (no `AudioMixerRenderThread`
  etc. among the 54 thread names -- compare the named list in the file).
  The only "Audio" string in the whole capture is a `ModLoad` line for
  `X3DAudio1_7.dll`, i.e. the DLL is present in memory but nothing is
  blocked waiting on it. The game thread (thread 0) stack is:
  `UGameEngine::Tick -> UWorld::Tick -> FTickTaskManager::RunTickGroup ->
  FTickTaskSequencer::ReleaseTickGroup ->
  FTaskGraphImplementation::WaitUntilTasksComplete -> ... ->
  FEventWin::Wait` -- this is the ordinary per-frame wait for parallel tick
  tasks to finish, not an audio fence.
* `cdb_thread0_t1.txt` -- taken several minutes later, after the second
  (60s) client timeout also failed. Game thread (thread 0) this time is at
  a **completely different location**: `UGameEngine::Tick -> UWorld::Tick
  -> FTickTaskManager::RunTickGroup -> FTickTaskLevel::QueueNewlySpawned`,
  i.e. mid-way through actual per-frame tick-function bookkeeping, not
  blocked in any `Wait` call at all.
* CPU sampling (`Get-Process -Id 31680` `.CPU` delta) across a 5-wall-second
  window showed **~4.5 CPU-seconds consumed** (~90% of one core) -- the
  process is actively churning, not idle-blocked. A true deadlock on a
  fence that's never signaled (as in the prior `-nosound` attempt's finding)
  would show near-zero CPU and a stack frozen at the exact same instruction
  across snapshots.

Conclusion: disabling the Audio Mixer subsystem via `-ini:` override
**genuinely eliminates the previously-documented audio-fence deadlock** --
the game thread is confirmed alive, ticking frames repeatedly, and moving
through normal per-frame logic across two independent snapshots taken
minutes apart. This is a materially different (and better) runtime state
than either prior attempt. **However, the RPC handshake still never
completes even though the engine is healthy and ticking.** This rules out
the audio subsystem as *the* blocker under this configuration and points
the remaining fault at CARLA's own RPC/networking layer (the `carla-server`
plugin's rpclib/asio-based acceptor) rather than at UE4 engine-level
audio-device enumeration.

## Deeper sanity check

Not applicable -- the client never connected (`get_server_version()` never
returned), so per the task instructions there is nothing further to sanity
check (spawning an actor, querying map info) since no working client
session was ever established.

## Cleanup

Both the shipping child (PID 31680) and launcher (PID 19804) were killed
via `Stop-Process -Force` after the investigation. Verified via
`Get-Process -Name "CarlaUE4*"` (empty) and `Get-NetTCPConnection -LocalPort
2000,2001,2002` (empty) that no orphaned instances or listening ports
remained. Note: two *pre-existing* orphaned `CarlaUE4-Win64-Shipping.exe`
processes (PIDs 13804, 14124, from an earlier, unrelated session, listening
on ports 2000-2002/20000-20002) were found running at the start of this
investigation and were also cleanly killed to establish a clean baseline
before the new launch.

## Verdict for GAP-017

`blocked_external`, unresolved, but narrowed further: the audio-fence
deadlock specifically is now ruled out as *this* run's blocker (a distinct,
reproducible difference from the `-nosound` attempt, confirmed via two
independent cdb snapshots and CPU sampling, not assumption). The RPC
handshake failure persists under a config where the engine is confirmed
non-deadlocked and actively ticking, which shifts the most likely fault
location to CARLA's RPC/networking layer itself. Remaining untried (not
attempted here, out of scope for this bounded check): tracing CARLA's own
`rpc-server`/`carla-server` plugin startup logs or attaching a debugger
specifically to whatever thread hosts the rpclib acceptor (no such thread
was identified by name in either snapshot -- CARLA's RPC dispatch may run
synchronously inside the game-thread tick, in which case the RPC server
should already be getting serviced each frame, which is itself now a new,
narrower open question this probe surfaces but does not answer). Per the
task's original scope, this was a one-shot bounded check and stops here
without escalating to OS audio device changes or UE4 source rebuild.
