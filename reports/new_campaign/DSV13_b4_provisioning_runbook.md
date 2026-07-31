# DSV13 — B4 Provisioning Runbook (human-executed)

**Model:** DeepSeek V4 Light · **Mode:** READ-ONLY authoring (reports only — nothing mutated) · **Task ID:** DSV13-RUNBOOK
**Branch:** `integration/governed-map-quality-20260729` · **Base SHA:** `2fdc8e501faf40f0bd3b29bc85e4e6780b083a69`
**Writer lock:** `DSV13-RUNBOOK` (acquired via canonical `WriterLock.acquire`; released after push)
**Verdict:** `B4_RUNBOOK_READY`

This runbook converts the DSV06 inventory (`reports/new_campaign/DSV06_b4_toolchain_preflight.md`) into an ordered, executable path for the human operator. It is grounded in the official CARLA 0.9.16 docs (`build_linux`, `tuto_M_add_map_package`, `tuto_M_add_map_alternative`) and in the decisions already pinned in AG03/AG05/AG07 (Track A = UE4.26 make-based build; `CARLA_GENERATED_ROAD` = no FBX required; §36A.7 = cook must run on a Linux/Docker host).

## Step 0 — Disk gate (do FIRST; verified today; currently FAILS)

| Drive | Free (verified 2026-07-31) | Verdict |
|---|---|---|
| F: | **111.7 GB** | ❌ insufficient |
| C: | 51.3 GB | ❌ insufficient |
| E: | 12.8 GB | ❌ (packaged CARLA lives here) |

- Official docs minimum: UE ~91 GB + CARLA ~31 GB ≈ **130 GB**. Project policy (AG07/DSV06): **≥200 GB headroom**; the Docker-based cook image alone is documented at **600–700 GB / ~4 h** for first build.
- **F: 111.7 GB is NOT enough. Free ≥250 GB on F: (or attach an external NVMe/USB4 SSD) BEFORE starting.** Verify after freeing: `df -h /mnt/f` in WSL, or `Get-PSDrive F` in PowerShell.
- Build inside WSL's native ext4 filesystem, **not** `/mnt/f` (9p mount is too slow for UE builds). Move the WSL distro there:
  ```powershell
  wsl --shutdown
  wsl --export Ubuntu F:\wsl\ubuntu-backup.tar
  wsl --unregister Ubuntu
  wsl --import Ubuntu F:\wsl\Ubuntu F:\wsl\ubuntu-backup.tar
  ```
  Pins to record: `wsl --status`, `uname -a`, free GB after import (`df -h ~`).

## Step 1 — WSL2 Ubuntu 20.04 + Docker Desktop

- Distro `Ubuntu` (WSL2) already exists on the host (DSV06 §1); ensure it is Ubuntu 20.04 (`lsb_release -a`) — CARLA 0.9.16 docs support 20.04/22.04; project pin: **20.04**.
- Create `C:\Users\admin\.wslconfig` (host has 47.7 GB RAM / 12 threads):
  ```
  [wsl2]
  memory=32GB
  processors=8
  ```
- Install CARLA build deps (exact Ubuntu 20.04 line from the 0.9.16 docs):
  ```sh
  sudo apt-get update
  sudo apt-get install build-essential g++-9 cmake ninja-build libvulkan1 python3 python3-dev python3-pip python3-venv autoconf wget curl rsync unzip git git-lfs libpng-dev libtiff5-dev libjpeg-dev aria2
  ```
- Install **Docker Desktop for Windows** (WSL2 backend) from docker.com; in Settings → Resources → WSL Integration → enable `Ubuntu`.
  ```sh
  docker --version && docker run --rm hello-world
  ```
- Pins: `python3 --version` (≥3.8), `cmake --version` (≥3.9), `docker --version`, `git-lfs --version`.
- Expected time: 0.5–1 h incl. downloads. Expected disk: ~5 GB (ext4, on F: after Step 0).

## Step 2 — GitHub ↔ Epic link (human-only, license gate)

- CARLA 0.9.16 uses a UE4.26 **fork** (`CarlaUnreal/UnrealEngine`, branch `carla`). Cloning is public, but `./Setup.sh` downloads licensed precompiled engine binaries — **an Epic Games account linked to GitHub is mandatory** (Epic's `ue4-on-github` guide: unrealengine.com/ue4-on-github).
- Actions: create/link Epic account → connect GitHub → accept UE EULA. Create a fine-grained PAT for GitHub (repos: contents) for the clone.
- Expected time: 10–20 min account work; allow **24–72 h** for Epic access activation (do this on day 1 — it is the first human action, parallel with Step 0).
- Verify: `ssh -T git@github.com` or a test clone of `https://github.com/CarlaUnreal/UnrealEngine.git` (HEAD visible).

## Step 3 — Clone + build UE4.26 (CARLA fork)

```sh
export UE4_ROOT=~/UnrealEngine_4.26          # add to ~/.bashrc
git clone --depth 1 -b carla https://github.com/CarlaUnreal/UnrealEngine.git ~/UnrealEngine_4.26
cd ~/UnrealEngine_4.26
./Setup.sh && ./GenerateProjectFiles.sh && make   # DO NOT use -j; clang parallelizes itself
```
- Disk: ~91 GB. Time: docs say 1–2 h; on this laptop (i7-8850H 6C/12T) budget **3–5 h**.
- Verify: `Engine/Binaries/Linux/UE4Editor` opens (WSLg on Windows 11 supports the GUI).
- **Pins to record (AG07 evidence):** `git rev-parse HEAD` (UE fork commit), `Engine/Build/Build.version` (changelist), `$UE4_ROOT`.

## Step 4 — Clone CARLA @ 0.9.16 + build (Track A, make)

```sh
export CARLA_UE4_ROOT=~/carla                  # add to ~/.bashrc
git clone -b ue4-dev https://github.com/carla-simulator/carla.git ~/carla
cd ~/carla && git checkout 0.9.16
./Update.sh                                    # downloads content (~30 GB; aria2 speeds this up)
make setup
make LibCarla
make PythonAPI
make launch                                    # editor smoke test (first shader load is slow)
make package                                   # packaged server; cook output lands here
```
- Disk: ~31 GB + build outputs. Time: **2–6 h** total on this host.
- Verify: `PythonAPI/carla/dist/carla-0.9.16-cp38-linux_x86_64.whl` exists (wheel name **also sources `carla_osm2odr_version`** — see DSV14 note).
- **Pins:** `git rev-parse HEAD` at tag `0.9.16`, content archive hash from `Util/ContentVersions.txt`, `du -sh ~/carla`, wheel filename.

## Step 5 — New `Dockerfile.carla_cook` + image digest (reproducibility pin)

Create `submission/infrastructure/ultimate_pipeline/cook/Dockerfile.carla_cook` (canonical, tracked) — a documented adaptation of CARLA's `Util/Docker` ingestion image:

```dockerfile
FROM ubuntu:20.04
# CARLA 0.9.16 Linux cook image — built from carla source at tag 0.9.16
# (see carla/Util/Docker for the unmodified upstream variant)
ARG CARLA_COMMIT
ENV CARLA_UE4_ROOT=/opt/carla
COPY --from=carla-src /carla /opt/carla            # stage: source build from Step 4
COPY --from=ue4-src /UnrealEngine_4.26 /opt/ue4    # stage: UE build from Step 3
ENV UE4_ROOT=/opt/ue4
RUN apt-get update && apt-get install -y python3 python3-pip xvfb && pip3 install -r /opt/carla/PythonAPI/carla/requirements.txt
WORKDIR /opt/carla
CMD ["python3", "Util/Docker/docker_tools.py", "--help"]
```
Build + record digest:
```sh
docker build -t carla_cook:0.9.16-$(cd ~/carla && git rev-parse --short HEAD) \
  -f submission/infrastructure/ultimate_pipeline/cook/Dockerfile.carla_cook .
docker images --digests carla_cook
# record the IMAGE DIGEST + full CARLA/UE commit pins into the toolchain pin manifest (DSV06 item 9)
```
- ⚠ Disk callout: a full UE-in-Docker image build needs **600–700 GB / ~4 h** (official docs). On this host that **requires Step 0 to have passed** (≥200 GB is the floor for the source build; the Docker image path needs the expanded disk). Alternative that skips the giant image: use the Step 4 **source-build editor** to cook (Step 6a) and keep Docker only for the final runtime ingestion image (`carlasim/carla:0.9.16`, `docker pull` + record its `RepoDigest` via `docker inspect --format '{{index .RepoDigests 0}}' carlasim/carla:0.9.16`).

## Step 6 — Trivial-XODR cook smoke test (CARLA_GENERATED_ROAD — no FBX needed)

**6a. Source-build cook (recommended, Track A).** A minimal handcrafted XODR (2 roads + 1 junction, EPSG:32632 header) placed at:
```sh
cp trivial_smoke.xodr ~/carla/Unreal/CarlaUE4/Content/Carla/Maps/OpenDrive/
cd ~/carla && make launch
```
Then, per the official manual-import tutorial (`tuto_M_add_map_alternative`): duplicate `BaseMap` → save as `trivial_smoke` in `Content/Carla/Maps/trivial_smoke/` → drag an **OpenDrive Actor** into the scene → `Add Spawners` + `Generate Routes` (reads the same-named XODR) → save level → close editor → `make package`.

**6b. Verify (PythonAPI, from the packaged server or `CarlaUE4.sh`):**
```sh
python3 -m pip install ~/carla/PythonAPI/carla/dist/carla-0.9.16-cp38-linux_x86_64.whl
python3 - <<'PY'
import carla
client = carla.Client("localhost", 2000)
print("server:", client.get_server_version())     # ← sources carla_osm2odr_version
print([m for m in client.get_available_maps() if "trivial_smoke" in m])
world = client.load_world("Carla/Maps/trivial_smoke")
print("load_world OK, map:", world.get_map().name)
PY
```
**Pass criteria:** `get_available_maps()` contains the new map; `load_world` succeeds; server version prints.
**Pins:** map name, server version, timings, disk used. This gate satisfies B4's closure action ("successful make build log + digest") and feeds AG07 evidence.

## Pin table (record into the toolchain pin manifest, DSV06 item 9)

| Item | Command | Pin |
|---|---|---|
| WSL | `uname -a` | kernel + distro version |
| UE4.26 fork commit | `git -C ~/UnrealEngine_4.26 rev-parse HEAD` | full SHA (branch `carla`) |
| UE changelist | `Engine/Build/Build.version` | changelist |
| CARLA commit | `git -C ~/carla rev-parse HEAD` | full SHA @ tag `0.9.16` |
| Content archive | `Util/ContentVersions.txt` | URL + SHA256 of tar.gz |
| PythonAPI wheel | `ls PythonAPI/carla/dist/` | `carla-0.9.16-cp38-linux_x86_64.whl` |
| Cook image digest | `docker images --digests carla_cook` | full digest |
| Runtime image digest | `docker inspect --format '{{index .RepoDigests 0}}' carlasim/carla:0.9.16` | full digest |
| Smoke test | Step 6b script | `get_server_version()` + map load OK |

## Explicit callouts

1. **F: 111.7 GB is likely insufficient — need ≥200 GB (docs floor ~130 GB; Docker cook path 600–700 GB).** Verified again 2026-07-31: 111.7 GB. Step 0 is a hard gate.
2. **The packaged `E:\CARLA\CARLA_0.9.16` CANNOT cook** (DSV06 §3: Shipping-only binary, no `UE4Editor.exe`, no `Engine\Source`, no `Setup.sh`). Keep it as the Windows runtime anchor only.
3. UE `make` must run without `-j` (docs warning — clang parallelizes itself).
4. Do Step 2 (Epic link) on day 1 — activation latency is the only human-wait item.
5. GPU (Quadro P3200, driver R570+) and RAM (47.7 GB) are adequate per DSV06 §1; UE editor GUI works via WSLg.
