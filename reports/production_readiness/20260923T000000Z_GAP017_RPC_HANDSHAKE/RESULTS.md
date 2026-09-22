# GAP-017 fresh RPC probe

Evidence was captured on 2026-09-23 using the packaged
`E:\CARLA\CARLA_0.9.16` distribution and the repository virtual environment.

* Python package: `carla 0.9.16` (`pip show carla`).
* Packaged server changelog: `CARLA 0.9.16`.
* Command: `CarlaUE4.exe -carla-server -nullrhi -carla-rpc-port=2000
  -windowed -ResX=640 -ResY=480`.
* The launcher PID was **not** the server PID.  It spawned
  `CarlaUE4-Win64-Shipping.exe` PID 28932, which owned port 2000 and reached
  5,899,157,504 bytes working set.  Harnesses must inspect the process tree,
  not require the launcher PID to own the socket.
* A live `carla.Client(...).get_server_version()` process produced no version
  output before controlled cleanup.  This run does not claim a completed
  30-second timeout because the initial launcher-PID ownership bug delayed
  the probe controller; it does prove no successful RPC response while the
  shipping process was live and listening.
* `cdb` attached to the actual shipping process.  The game thread stack in
  `cdb_shipping_stack.txt` is:
  `FEventWin::Wait -> FAudioCommandFence::Wait ->
  FAudioDeviceManager::UpdateActiveAudioDevices -> UGameEngine::Tick`.
  It is not the previously observed NVIDIA `nvwgf2umx.dll/OpenAdapter10`
  path.
* Existing `carla_server.log` contains repeated `error sending data : An
  existing connection was forcibly closed by the remote host`; those lines
  are historical (2026-08-04), so they are context only, not attribution for
  this fresh probe.

Result: `BLOCKED_EXTERNAL`, now narrowed to a live server main-thread stall
in the audio-fence/update path while the RPC socket is listening.  This is
not map-content evidence and not a reason to modify generated map geometry.
The next external investigation is audio-device/service configuration or a
CARLA/UE runtime environment owner; no firewall exception was made and no
system configuration was changed.

Artifacts: `launch.txt`, server/client stdout/stderr logs,
`cdb_shipping_stack.txt`, `server_process_after_client.txt`, and
`port_after_client.txt` in this directory.
