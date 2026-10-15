# M6 — Runtime Execution Spec

**Entry precondition: `RUNTIME_HOST_ADMISSION=PASS`.** (Runtime does not strictly require
a completed M5B — a stock CARLA map such as `Town10HD_Opt` or `Grid0828` can run. It does
require a **fully admitted host**.)

Current host status: `DENIED_EXTERNAL`. Written for another machine.

---

## 0. The rule that matters most

> **Port listening is not CARLA success. An editor window is not a qualified host.**

Success is an **actual RPC response**. The generating host has a standing rule on this:
*"RUNTIME_READY confirmed by real RPC response, not by port listening alone."*

A recorded failure shows why this is not pedantry: with `-nullrhi` the process stayed
alive, burned CPU across 59 threads, held a flat working set, and left VRAM at **0 MiB
of 6144** across all 43 samples — and never once serviced RPC. Nothing was wrong with the
GPU. The process was livelocked. A port check would have been inconclusive; the RPC call
was not.

---

## 1. Runtime identity

| Item | Expected |
| --- | --- |
| CARLA server version | **0.9.16** |
| Python client | `carla==0.9.16` |
| Client/server match | **must be exact** |

**Version matching is not fail-closed in-repo.** Existing preflight records
`get_server_version()` and continues on failure; mismatch produces only an advisory
warning. **You must add the explicit comparison yourself.** Do not rely on upstream
tooling for this gate.

### Map identity states — do not conflate

| Package | State | Meaning |
| --- | --- | --- |
| `Grid0828` | `RUNTIME_IDENTITY_ESTABLISHED` | verified live identity; fingerprint recorded |
| `Ingolstadt` (authoritative) | `BLOCKED_COOK_REQUIRED` | **absent from the runtime cook registry** |

`Grid0828` observed name is the triple-path form `Grid0828/Maps/Grid0828/Grid0828`.
Structural fingerprint (light mode): `32e4f7908f87fa9e69bc795cfa8281aa7df73ee86bc795ae4d1ea82d850210fa`,
223 actors, 222 traffic signs, 14 traffic lights, 0 landmarks.

**On an admitted host, expect `Ingolstadt` to be un-cooked unless M5B completed and the
map was promoted into the runtime registry.** A successful editor smoke test tells you
nothing about map availability.

**Claim boundary:** `AUTO_COOK_RECEIPT.json` is an **offline FBX-generation record, not a
cook receipt** — no editor was invoked. Do not read its `status: PASS` as a cook success.

## 2. Ports

| Port | Role |
| --- | --- |
| 2000 | RPC |
| 2001 | Streaming |
| 2002 | Secondary |

Client host is `127.0.0.1`. Prefer env overrides (`UP_CARLA_RPC_PORT`,
`UP_CARLA_STREAMING_PORT`) over hard-coded ports. Protocol/transport annotations were
never recorded in-repo — confirm the transport on the new host rather than assuming it.

For concurrent runs, use an isolated lease (e.g. 2004/2005), as prior evidence did.

## 3. Runtime command template

```bash
# Package directory containing CarlaUE4-Win64-Shipping.exe
"CARLA_PACKAGE_DIR/CarlaUE4-Win64-Shipping.exe" \
  -carla-server \
  -carla-rpc-port=2000 \
  -carla-streaming-port=2001 \
  -RenderOffScreen \
  -quality-level=Low \
  -nosound \
  -log
```

In-repo launch defaults: `--rpc-port 2000 --streaming-port 2001`, extra args
`-RenderOffScreen -quality-level=Low -nosound`, `--wait-port-seconds 180.0`,
`--rpc-timeout 25.0`.

If invoking the editor build instead (not the packaged runtime), the recorded flags are
`-carla-server -carla-rpc-port=2000 -windowed -ResX=640 -ResY=480 -nosound`.

### Launch + probe using in-repo tooling

```bash
python tools/carla_runtime_launch.py \
  --rpc-port 2000 --streaming-port 2001 \
  --wait-port-seconds 180.0 --rpc-timeout 25.0 \
  --json-out reports/m6_launch.json
# exit 0 = RUNTIME_READY, exit 2 = BLOCKED_ENVIRONMENT

python tools/carla_runtime_probe.py --json-out reports/m6_probe.json
# Probe only; never launches. RPC order:
#   get_server_version -> get_available_maps -> get_world -> get_map().name -> get_snapshot().frame
```

Both tools use **PID-ownership discipline**: they terminate only their own PID.
**Preserve that.** Never issue a global `taskkill` by image name.

### RPC smoke (explicit, fail-closed on version)

```python
import carla
c = carla.Client("127.0.0.1", 2000)
c.set_timeout(30.0)
try:
    sv = c.get_server_version()
    cv = c.get_client_version()
    assert sv is not None, "no RPC response"
    assert sv == cv == "0.9.16", f"version mismatch server={sv} client={cv}"
    w = c.get_world()
    print("map:", w.get_map().name, "frame:", c.get_snapshot().frame,
          "maps:", len(c.get_available_maps()))
finally:
    c.disconnect()
```

Required runtime values, matching the existing runtime requirements doc: reachable
server, verified world identity, generated and manual map hashes, sensor calibration
hash, route/weather contracts, **synchronous mode with fixed delta**, attached listeners,
and complete frames. Record everything in machine-readable manifests.

## 4. M6 exit criteria

| # | Criterion | Proof |
| --- | --- | --- |
| 1 | `RUNTIME_HOST_ADMISSION=PASS` from this host | preflight report, this run |
| 2 | Packaged server starts and stays up | server log, no orphan |
| 3 | `get_server_version()` returns `0.9.16` | **real RPC response** |
| 4 | Client version `0.9.16`, exact match | explicit comparison |
| 5 | `get_world()` + `wait_for_tick()` succeed | RPC, not port |
| 6 | Map identity verified | `get_map().name` + fingerprint |
| 7 | Version mismatch **not** tolerated | fail-closed assert |
| 8 | No orphan processes after teardown | PID-scoped termination |

All eight are required. The generated runtime receipt pattern is:

```
verdict=RUNTIME_READY   get_server_version=0.9.16   world_get_map=<name>
snapshot_frame=<n>      get_available_maps_count=<n>   rpc=2000 listening
```

If the server responds but the map is absent, that is a **map** failure, not a host
failure. Record it as such and return to M5B §9 criterion 4.

## 5. Known runtime fragilities — read before blaming the map

| Symptom | Likely cause |
| --- | --- |
| Process alive, CPU busy, VRAM 0 MiB, no UE log | **CPU livelock**, not GPU. Never reaches RPC. |
| Editor opens then wedges during waypoint expansion | Reproduced on `Grid0828`; environment-specific. |
| RPC refuses connections after a prior crash | Leaked `synchronous_mode=True` from a dead owner. |
| `load_world()` fails with sync mode | No live tick owner. Do not enable sync without one. |
| "Unkillable" process | `taskkill` from Git Bash mangles `/F` → `F:/` and fails silently. Use PowerShell `Stop-Process`. |
| Engine binary missing from `Engine/Binaries/Win64` | Endpoint-security quarantine, not a build failure. |
| Massive GPU watchdog dumps, no Event 4101 | `LiveKernelEvent` 141 (display TDR). Environment fault; maps are exonerated. |

**Anti-pattern:** treat a livelock as a slow start and wait longer. It does not resolve.
Kill by owned PID and change the configuration.

## 6. Process and hygiene rules

- Terminate **only PIDs you own**. No global image-name kills.
- Use PowerShell `Stop-Process`, not `taskkill` from Git Bash.
- Check for orphaned `UE4Editor.exe` before starting — orphans have survived ~25 min
  after their parent's exit and can hold Content-tree file locks that break later cooks.
- **Do not disable, bypass, or weaken endpoint security.** If an exclusion cannot be
  created through documented, authorized means, move to another host.
- Do not purge DDC to "fix" slowness; preserve the evidence first.
- The offline CI workflow reports runtime verification as `NOT_RUN` by design. Only the
  self-hosted runtime workflow may claim live evidence — do not relabel offline output
  as live.

## 7. Honesty boundary for reporting

| Claim | Requires |
| --- | --- |
| "Host admitted" | all five gates `PASS`, this host |
| "CARLA reachable" | an actual RPC response |
| "Map loaded" | `get_map().name` verified + identity fingerprint |
| "Runtime verified" | an actual RPC response — **never** port listening |
| "Not run" | everything else |

Reporting `NOT_RUN` is always correct and always safe. Reporting a pass that rests on a
window opening, a listening port, or a cook log is not.

On success, attach the preflight report, the launch receipt, the probe output, and the
map identity record as machine-readable evidence.
