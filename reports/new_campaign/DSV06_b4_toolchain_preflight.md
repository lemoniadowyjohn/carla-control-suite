# DSV06 — B4 Source-Toolchain Readiness Pre-Flight

**Model:** DeepSeek V4 Light · **Mode:** READ-ONLY inventory (no installs) · **Task ID:** DSV03-06-REPORTS
**Verdict:** `B4_PREREQS_INVENTORIED` — blockers: **UE4.26 source access, CARLA 0.9.16 source, Docker, build deps, disk headroom, toolchain pin**

## 1. Host prerequisites

| Item | Status | Value |
|---|---|---|
| WSL | ✅ present (partial) | `Ubuntu` (WSL2, stopped) + `docker-desktop` (WSL2, default, stopped); no WSL1 |
| Docker | ❌ **GAP** | `docker --version` not found; only a stopped docker-desktop WSL distro |
| git-lfs | ✅ | `git-lfs/3.5.1` (filters configured, `required=true`) |
| Disk free | ⚠️ **GAP** | C: 47.1 GB · E: 12.8 GB · F: **111.7 GB** · G: 7.7 GB · H: 16.6 GB → F: is the only viable build target |
| CPU | ✅ | Intel Core i7-8850H @ 2.60 GHz, 6C/12T |
| RAM | ✅ | 47.7 GB (UE4.26 needs 16–32 GB) |
| GPU/driver | ✅ | Quadro P3200 Max-Q, driver 32.0.15.7322 (≈R570/573) + Intel UHD 630 + 2× DisplayLink |
| `.wslconfig` | absent | no memory/processor limits set |

## 2. Source-tree scan (10 worktrees + carla_governed + submission_ready mirrors)

**ZERO hits for:** CARLA source trees (`CarlaUE4/` with `Source/`), `Setup.sh`, `GenerateProjectFiles.sh`, CARLA `Makefile`, `*.uproject`, `UnrealEngine*` dirs, packaged `CarlaUE4*.exe` in any worktree.

Dockerfile inventory (25 total, none CARLA-build related):
- **13× `Dockerfile.yolo_smoke`** (canonical `submission/infrastructure/ultimate_pipeline/hpc/Dockerfile.yolo_smoke` + mirrors) — python:3.11-slim pytest smoke → **EXCLUDED, unrelated to CARLA cooking**
- 11× `carla_mcp_oneclick/Dockerfile` (python:3.11-slim MCP server) — unrelated
- 1× esmini runtime Dockerfile (`external/esmini/resources/dockers/Dockerfile`, untracked) — unrelated

External CARLA (outside repos, the only CARLA on the host): `E:\CARLA\CARLA_0.9.16\` — `CarlaUE4.exe` + `CarlaUE4\` (Binaries/Config/Content/Plugins only, **no Source/**, has `.uproject`) + `Engine\` (**no Engine\Source, no GenerateProjectFiles.bat, no UE4Editor.exe**) + PythonAPI/HDMaps/Import/ + a ubuntu:20.04 **runtime** Dockerfile + `carla-0.9.16-cp312…whl`. **Packaged release tree — no editor/toolchain.**

## 3. enter_carla.ps1 — PACKAGED target, cannot cook

- Single tracked copy: `submission/infrastructure/ultimate_pipeline/tools/enter_carla.ps1`
- Bootstraps only (dot-sources `thesis_env_preset.ps1`); target set at `thesis_env_preset.ps1:19`: `$env:CARLA_EXE = "E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"`
- **Explicit finding: `CarlaUE4.exe` is a packaged Shipping build (`CarlaUE4-Win64-Shipping.exe` present, no `UE4Editor.exe`, no `GenerateProjectFiles.bat`, no `Engine\Source`, no `CarlaUE4\Source`, no `Setup.sh`). It can only run as a server — it CANNOT import/cook/package maps.**

## 4. Epic / UE access markers

Zero `github.com/EpicGames` / `EpicGames/UnrealEngine` URLs, zero Epic-account/access notes, zero `*Get*UE*` scripts anywhere. Only planning references: `reports/architecture_gate/{AG03,AG05,AG07,UNREAL_COOKING_PARAMETERS}.md` (Track A = make-based cook on UE4.26, B4 listed as `BLOCKED_TOOLCHAIN`), `Problems.md:1713`/PROB-101, `read_only_map_readiness_audit/…/06_unreal_cooking_readiness.md` (no pinned UE version/branch), `CODEX_FIX_PROMPTS.md` D3, `settings.py` install-location hints.

## 5. Ordered B4 provisioning checklist

| # | Item | Status | Action |
|---|---|---|---|
| 1 | Disk (~120–150 GB) | ❌ GAP | Build on **F:** (111.7 GB free) or free C: |
| 2 | WSL2 Ubuntu | ⚠️ partial | `wsl -s Ubuntu`; `apt update`; optional `~/.wslconfig` (32 GB / 8 procs) |
| 3 | Docker CLI/Desktop | ❌ GAP | Install Docker Desktop (or engine in Ubuntu) |
| 4 | UE4.26 source access | ❌ GAP | Epic account → link GitHub → UE EULA → UE4.26 + CARLA fork `carla-simulator/UnrealEngine` (access via CARLA) |
| 5 | CARLA 0.9.16 source | ❌ GAP | `git clone -b 0.9.16` + submodules (LFS ready ✅); **pin commit** |
| 6 | Linux build deps | ❌ GAP | clang-8/9, cmake ≥3.9, ninja, python3.7+ (per `Util/Install.md`) |
| 7 | Engine build / cook | ❌ GAP | `make setup LibCarla PythonAPI launch import package` (Track A); record image digest + pins (AG07 evidence) |
| 8 | Runtime sanity | ✅ partial | Packaged `E:\CARLA\CARLA_0.9.16` server-only; GPU/RAM adequate — keep as runtime anchor, not toolchain |
| 9 | Toolchain pin manifest | ❌ GAP | Track UE4.26/CARLA-0.9.16 commit pins + digest (audit 20260730 finding) |
