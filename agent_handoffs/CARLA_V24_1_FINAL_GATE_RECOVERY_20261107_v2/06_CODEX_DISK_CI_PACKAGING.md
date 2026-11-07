# CODEX / runner owner — safe disk recovery and exact-SHA full validation

**Scope:** resource triage, test/packaging plan and only permissioned execution. Do not delete any existing data or push code to GitHub from this prompt alone. C: reported ~455 MB and D: ~548 MB free. The 8k+ offline suite, wheel/sdist build and CI are NOT RUN for candidate `8fcd8c79` (must resolve full SHA locally).

## 0. Read-only capacity census
Record UTC, host, OS, Python, filesystem types, free/total bytes, quota restrictions and writable mount points with bounded Windows PowerShell commands:
```powershell
Get-CimInstance Win32_LogicalDisk | Select-Object DeviceID,Size,FreeSpace,FileSystem
Get-PSDrive -PSProvider FileSystem | Select-Object Name,Root,Free,Used
```
Verify whether E:, F:, G: or another scratch disk has sufficient **real**, writable headroom, without revealing private file content. Do not use a folder merely because its path exists. Measure known/estimated test peak scratch demand and archive size from prior primary receipts; set a conservative buffer and preflight available bytes before any run. Avoid broad recursive directory crawls on resource-starved disks.

## 1. Safe remediation plan — no destructive side effects
- Propose relocation of **new** temp, JUnit and build artifacts to an authorized sufficiently spacious volume or an authorized separate Windows/Linux CI runner. Preserve old evidence and worktrees.
- For an *approved* isolated test runner, configure temporary paths such as `$env:TEMP`, `$env:TMP`, `$env:PYTHONDONTWRITEBYTECODE='1'`, `PIP_CACHE_DIR`, `PYTEST_ADDOPTS`, pytest `--basetemp`, `--junitxml`, and build output so C/D do not fill. Validate paths and permissions. Do not set PATH/environment globally, modify system settings, or install packages without authorization.
- Inventory candidate cleanup proposals **only** with type, path, size, owner, retention risk and backup/rollback. `git clean`, cache purge, trash, deleting audit ZIPs, changing Windows profile dirs or resetting a worktree are all forbidden without explicit owner signoff. If no safe plan, stop with `BLOCKED_ENV_DISK`.

## 2. Full offline suite and platform gates — only after approval
- Require actual **new full candidate SHA/tree**, source clean state, manifest, W-B/W-F cross-provider verdicts, W-D acceptance authority, no writer conflict and safe headroom.
- Run correct pytest selection collected from source (historically ~8k, but discover exact), with stable pinned dependencies and no unsanctioned filtering, maxfail, deselection, skip manipulation, warning suppression or threshold change. Preserve stdout/stderr, full failure nodeids/tracebacks, JUnit, exit code and counts; distinguish collection skips, xfail and runtime tests.
- Run W-D original accepted 26-nodeid suite or explicitly approved replacement and critical OpenCode negative controls. Platform-specific Windows-native mutex/CARLA integration tests must use authorized Windows executor and provide actual native evidence; Linux-skip is NOT Windows PASS.
- Run Linux full/relevant suite on approved runner using exact candidate SHA and pinned env. Classify OS-inapplicable tests explicitly, don't silently omit.
- Run remote GitHub Actions for exact candidate SHA **only after explicit authorization** to create/push a dedicated nonprotected CI review ref or approved dispatch method. Use GitHub run IDs, check-run conclusions, exact head SHA, job logs and artifacts; empty filtered PR-run list is not evidence of no push run. Remote CI cannot be substituted with local Linux tests.

## 3. Packaging and artifact provenance
After disk/authorization gates, build wheel and sdist from clean, exact candidate source with pinned toolchain in isolated temp/output, e.g. `python -m build --wheel --sdist --outdir <approved-build-output>` (example command, do not execute blindly). Verify artifact manifests, installed files, imports, hashes, bundled assets/contracts, unexpected secrets/absolute host paths, source tree/commit, reproducibility conditions and isolated install smoke tests. Compare repeated builds only under controlled timestamps/build settings; nondeterministic metadata must be diagnosed, not hidden.

## 4. Evidence and decision
Write `DISK_CAPACITY_CENSUS.json`, `SAFE_RUNNER_PLAN.md`, `RESOURCE_AUTHORIZATION_REQUEST.md` (if needed), `FULL_SUITE_RECEIPT.json`, `PLATFORM_CI_MATRIX.csv`, `PACKAGE_BUILD_PROVENANCE.json`, `CI_RUN_LINKS.md`, `SHA256SUMS.txt`. If blocked, write receipts with `executed=false` and explicit resource/authorization cause; do not forge zero exit codes or CI URLs. No automatic publication, protected merge, live CARLA or model training.
