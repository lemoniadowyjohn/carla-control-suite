# Codex PROMPT MM: build CARLA's Unreal Engine fork + CARLA from source on an external drive

## Context

A same-session investigation (2026-09-14/15) confirmed no Unreal Engine, RoadRunner, or cooking
automation exists on this machine, and the existing CARLA install
(`E:\CARLA\CARLA_0.9.16`) is a packaged Shipping binary that can only *load* pre-cooked content, not
*cook* new content. To actually cook this pipeline's generated map into a real CARLA/UE4 map (buildings
rendered, no artificial safety walls -- see `ultimate_pipeline/enrichment/osm2world_runner.py` and the
standalone-OpenDRIVE-mode limitations documented in CARLA's own docs), CARLA's Unreal Engine 4.26 fork
and CARLA itself must be built from source.

Verified today against CARLA's official docs (carla.readthedocs.io): building CARLA + UE4 needs
**~170GB** (35GB CARLA + 95-135GB engine) on Windows, natively (not via Docker -- CARLA's Docker-based
ingestion path needs 600-700GB and is Linux/WSL2-only, ruled out as worse on disk for this machine).
None of this machine's existing drives (C: ~12GB free, E: ~12GB free, F: ~65GB free, D: a small ~4GB-free
removable drive) have enough headroom -- **this task targets a NEW external drive the user is expected
to have connected**, not any existing drive.

## Hard prerequisite gate -- check this FIRST, before touching anything

This task depends entirely on interactive/account setup only the user can do (Visual Studio 2022 with
the "Desktop development with C++" and "Game development with C++" workloads; CMake >=3.28; Ninja; Git
with Git LFS; a GitHub account linked to Epic Games' organization for UE4 source-repo access). **Do not
attempt to install any of these yourself, and do not attempt to work around a missing one.**

Before doing anything else:
1. Confirm a target external drive is specified (expect an environment variable or a documented
   convention -- e.g. `UP_UE4_BUILD_DRIVE`; if none is set/discoverable, STOP and report exactly that
   as the blocker, do not guess a drive letter).
2. Confirm that drive has at least 250GB free (170GB + real headroom). If not, STOP and report the
   actual free space found.
3. Confirm Visual Studio 2022 with the required C++ workloads is installed (e.g. via `vswhere.exe`
   under `%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\`). If missing or the workloads aren't
   present, STOP and report exactly what's missing.
4. Confirm `cmake --version` >=3.28, `ninja --version`, and `git lfs version` all resolve on PATH. If
   any are missing, STOP and report exactly which.
5. Confirm git can actually authenticate against the CARLA UE4 fork's private/gated repo (a plain
   `git ls-remote` against the fork URL is a safe, read-only way to check this without cloning). If
   authentication fails, STOP and report that the GitHub-Epic account link likely isn't active yet
   (per Epic's own process this can take time after linking) -- do not attempt to bypass this.

**If any prerequisite check fails, stop entirely, write a clear status report explaining exactly what's
missing, and do not proceed to cloning/building.** This is expected and correct behavior if the user
hasn't finished their own setup steps yet -- report it plainly, it is not a failure of this task.

## Task (only once every prerequisite above is confirmed present)

Work through these as distinct, resumable checkpoints. After each one, write/update a status file (see
Evidence below) recording pass/fail before moving to the next -- if this task's own execution budget
runs out partway through, the next invocation must be able to resume from the last completed checkpoint
rather than restarting from scratch.

1. Verify (do not blindly assume) which Unreal Engine version this specific CARLA 0.9.16 release
   expects, by checking CARLA's own build documentation/changelog for that exact version tag. Report
   this explicitly before cloning -- getting this wrong wastes a multi-hour clone+build.
2. Clone CARLA's UE4 fork onto the external drive at a **short path** (e.g. `<drive>:\UE4\`, not
   deeply nested -- UE4's build system is known to hit Windows' legacy 260-character path limit).
   Confirm Windows long-path support
   (`HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled`) is enabled first; if not,
   report that as a blocker requiring the user's own registry change (do not modify system registry
   settings yourself).
3. Run the engine's `Setup.bat` then `GenerateProjectFiles.bat`, then build (via `RunUAT` or the
   generated Visual Studio solution) -- this step alone can take multiple hours. Checkpoint the result.
4. Clone CARLA's own source onto the same external drive (a separate short path, e.g.
   `<drive>:\CARLA\`), set `UE4_ROOT` to the step-2 path, run `make setup`, `make PythonAPI`,
   `make build`. Checkpoint each.
5. Final verification: confirm `UnrealEditor.exe` (or `UE4Editor.exe`) launches without error, and
   `make launch` from the CARLA source opens the Editor with the CARLA project loaded.

## Evidence

Write a dated status artifact to
`reports/production_readiness/<TIMESTAMP>_UE4_CARLA_SOURCE_BUILD/BUILD_STATUS.md` (and a
machine-readable `BUILD_STATUS.json`) recording: target drive + paths used, engine version used, and a
per-checkpoint pass/fail/blocked table with exact error text for anything that failed. This is
infrastructure state, not a code change -- do not expect this task to modify any pipeline code in
`ultimate_pipeline/`.

## Constraints

- Do not touch C: or E: for any part of this build -- everything lives on the external drive.
- Do not install Visual Studio, CMake, Ninja, Git, or attempt any GitHub/Epic account linking yourself
  -- these are the user's own prerequisite actions, gated and checked above.
- Do not modify Windows registry settings (long-path support) yourself -- report if it's needed.
- New commits only for the evidence artifact, never amend. Never force-push. Never skip hooks.
- Full test suite via bare `pytest` must stay green (this task shouldn't touch pipeline code, so this
  should be a trivial check, but confirm it anyway).
- Push your branch and report status; do not merge into `integration/session-batch1-20260912` yourself.
- If a build step is going to take longer than your own reasonable execution budget, stop at the last
  clean checkpoint, report exactly how far you got and what the next resumed invocation should do next
  -- do not leave the external drive in a half-built, unrecorded state.
