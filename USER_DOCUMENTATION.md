# CARLA Ops Studio - User Documentation

**Version:** 1.0.0 (Phase 1 Offline Release)  
**Date:** 2026-10-15  
**Status:** `OFFLINE_RELEASE_VERIFIED` — Live validation requires separate operator approval

---

## Overview

CARLA Ops Studio is a PyQt6 desktop application for operating CARLA 0.9.16 simulator
sessions with full governance, safety controls, and evidence-based workflows.

**Key principle:** *No control without a backend API.* Every interactive element is
either bound to a verified service contract or explicitly disabled with a cited reason.

---

## Installation

### Prerequisites

| Component | Version | Notes |
|-----------|---------|-------|
| Python | 3.10 – 3.12 | 3.12.2 tested |
| CARLA client | 0.9.16 | `pip install carla==0.9.16` |
| Discrete GPU | ≥6 GiB VRAM | Required for live simulator; offline mode works without |
| OS | Windows 10/11 | Linux/macOS deferred (Windows-specific assumptions) |

### Quick Start (Offline Mode)

```powershell
# 1. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# 2. Install with GUI and runtime extras
pip install -e ".[gui,runtime,geometry,geo,visualization]"

# 3. Launch in offline/mock mode
carla-ops
# or
python -m ultimate_pipeline.gui.cli
```

The application starts in **SHARED_READONLY** mode with no simulator connection.
All mutating controls are disabled. Navigate screens via the sidebar or `Ctrl+K`
command palette.

### Installation Profiles

| Profile | Command | Use Case |
|---------|---------|----------|
| Offline GUI | `pip install -e ".[gui,geometry,geo,visualization]"` | Development, testing, documentation |
| Full runtime | `pip install -e ".[gui,runtime,geometry,geo,visualization]"` | Live simulator operations |
| Development | `pip install -e ".[gui,runtime,geometry,geo,visualization,dev]"` | Contributing, running tests |
| Headless CLI | `pip install -e ".[runtime,geometry,geo,visualization]"` | CI, scripting, no Qt |

**OpenCV conflict:** The `gui` extra uses `opencv-python-headless`; the `perception`
extra uses `opencv-python`. They are mutually exclusive. `repo_health.dependency_conflicts()`
detects this at `up health`.

### Verification

```powershell
# Verify installation without launching GUI
carla-ops --verify-install

# Run regression tests (requires QT_QPA_PLATFORM=offscreen)
$env:QT_QPA_PLATFORM="offscreen"
pytest tests/unit/test_gui_qt_shell.py tests/unit/test_gui_qt_runtime_pages.py -q
```

Expected: **380 tests passing, 1 skipped**.

---

## Application Screens (17 Routes)

| Route | Title | Status | Description |
|-------|-------|--------|-------------|
| `01` | Home | ✅ Implemented | Mode badge, session authority, evidence state, map identity |
| `02` | Environment Profiles | ✅ Implemented | Searchable configurator, staged diffs, atomic profiles |
| `03` | Connection & Diagnostics | ✅ Implemented | 5-stage health ladder, version gate, destructive action confirm |
| `04` | World & Time | ✅ Implemented | Synchronous mode, delta seconds, tick authority |
| `05` | Maps, GIS & Cooking | ✅ Implemented | Source/generated/cooked/runtime layers; cook blocked (UE4.26) |
| `06` | Traffic Manager | ✅ Implemented | WRITE_ONLY badge; 0 confirmed settings; restore unavailable |
| `07` | Actors & Routes | ✅ Implemented | Owned actors count; external actors preserved; teardown order |
| `08` | Sensors & Streams | ✅ Implemented | Callback metrics ONLY when recorded; radar/GNSS/IMU unavailable |
| `09` | Calibration Workbench | ✅ Implemented | Intrinsics/extrinsics; reprojection NOT MEASURED; drift NOT MEASURED |
| `10` | Perception & Localization | ⏸️ Placeholder | Tied to Prompt 08 (BL-35); no model weights exist |
| `11` | Scenario Test Studio | ✅ Implemented | Experiment registry (injected via port); live mutation blocked |
| `12` | Operational Fuzzer | ✅ Implemented | Dry-run validator; live Start requires Q22 lease; offline families only |
| `13` | QA Gates | ✅ Implemented | Gate suite viewer; never authors PASS; NOT_SUPPLIED unless real run |
| `14` | Experiments & Runs | ✅ Implemented | Experiment catalog; last verdict NOT_EVALUATED |
| `15` | Job Control | ✅ Implemented | Three lock authorities (REPO_WRITER, WORKTREE_LEASE, MACHINE_LEASE) |
| `16` | Diagnostics & Logs | ✅ Implemented | Audit journal, evidence freshness, service availability |
| `17` | Settings, Safety & Help | ✅ Implemented | Non-secret preferences, keyboard shortcuts, accessibility info |

**Navigation:** Click sidebar, use `Ctrl+K` command palette, or `Alt+1`–`Alt+9` shortcuts.

---

## Key Concepts

### Session Authority

| Authority | Mutating Controls | Description |
|-----------|-------------------|-------------|
| `SHARED_READONLY` | ❌ Disabled | Default; observes shared world only |
| `EXCLUSIVE_TICK` | ✅ Enabled | Grants tick ownership; restores on release |
| `EXCLUSIVE_WORLD` | ✅ Enabled | Full world mutation; map travel checked |
| `EXCLUSIVE_TM_PORT` | ✅ Enabled | Traffic Manager port claim |

**No blanket live control is ever granted.** Every mutating action requires explicit
confirmation and the appropriate authority.

### Truthfulness Invariants

| Invariant | Enforcement |
|-----------|-------------|
| No unmeasured value displayed as a number | `NOT MEASURED` / `NOT_EVALUATED` badges |
| No historical metric shown as live | `STALE_OR_UNBOUND` banners on GAP-026, tile_frame_consistency |
| No fabricated PASS verdicts | QA Gates shows `NOT_SUPPLIED` unless real suite executed |
| Every disabled control states its reason | `file:line` reference in accessible description |
| WRITE_ONLY values are badged | Traffic Manager, map enumeration when unsupported |
| No swallowed exceptions | 11 sites surface warnings via audit journal |
| No unmeasured coverage displayed | Coverage shown only when instrumentation exists |

### Evidence Vocabulary

| Status | Meaning |
|--------|---------|
| `PASS` | Executed and verified |
| `FAIL` | Executed and failed |
| `BLOCKED_EXTERNAL` | Requires operator action (cooking, lease, weights) |
| `NOT_EVALUATED` | No evidence collected |
| `INCONCLUSIVE` | Evidence exists but no owner-approved threshold |
| `STALE_OR_UNBOUND` | Historical; not bound to current map pin |

---

## Configuration

### Preferences (Non-Secret Only)

Saved to `%LOCALAPPDATA%\CARLA_Ops_Studio\carla_ops_gui.json` (Windows) or
`~/.config/carla_ops_studio/carla_ops_gui.json` (Linux/macOS).

| Key | Description |
|-----|-------------|
| `theme` | `light`, `dark`, `system` |
| `last_route` | Restored on launch (validated against route registry) |
| `column_widths` | Per-screen table column widths |
| `window_geometry` | Position and size |

**Secrets are NEVER persisted.** Keys matching `*_token`, `*_secret`, `*_key`,
`*_password`, `Bearer *`, `ghp_*` are rejected at any nesting depth.

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `QT_QPA_PLATFORM=offscreen` | Force offscreen rendering (CI/testing) |
| `CARLA_GUI_PROFILE` | Default theme/profile name |
| `CARLA_GUI_CONFIG_DIR` | Override config directory |
| `UP_TILE_QA_DISABLE_STREAMING=1` | Disable streaming in port probe |

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+K` | Command palette (search routes) |
| `Alt+1`–`Alt+9` | Navigate to route 1–9 |
| `F5` | Refresh current screen |
| `Ctrl+R` | Reload preferences |
| `Ctrl+Q` | Quit |
| `Esc` | Close dialog / cancel operation |

---

## Fuzzer Operations

### Offline Mode (Always Available)
- 15 mutator families (3 config-bound, 4 map, 8 simulator-guarded)
- Deterministic replay with seed + fingerprint
- Shrinking with budget and cancellation
- 12 GUI-side oracles (XML, lane, actor, sensor, TM, determinism, sync, geometry)

### Live Mode (Requires Q22 Lease)
```
Prerequisites:
  1. Dedicated CARLA server (non-shared)
  2. Exclusive authority grant (EXCLUSIVE_WORLD + EXCLUSIVE_TM_PORT)
  3. Q22 isolated server lease acquired
  4. All budgets configured (actor cap, sensor cap, VRAM, wall-clock)
  5. Typed confirmation: "START LIVE FUZZER lease=<ID>"
```

**Simulator-guarded families are NEVER executed in offline mode.** They are built
and registered but the `live Start` control remains `DISABLED` with reason
`BLOCKED_EXTERNAL: no exclusively owned isolated server lease (Q22)`.

---

## Troubleshooting

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `ModuleNotFoundError: PyQt6` | GUI extra not installed | `pip install -e ".[gui]"` |
| `ModuleNotFoundError: cv2` | OpenCV not installed | `pip install opencv-python-headless` |
| `carla` not importable | CARLA client not installed | `pip install carla==0.9.16` |
| GUI shows `NOT MEASURED` everywhere | No live simulator connected | Expected in offline mode |
| `carla-ops` command not found | Package not installed in editable mode | `pip install -e ".[gui]"` |
| Qt platform plugin error | `QT_QPA_PLATFORM` not set for CI | `set QT_QPA_PLATFORM=offscreen` |
| OpenCV version conflict | Both `opencv-python` and `opencv-python-headless` | Use only one extra; run `up health` |

---

## Unresolved Limitations (Honest Disclosure)

| Item | Status | Impact |
|------|--------|--------|
| Route 10 (Perception/Localization) | Deferred (BL-35) | No model weights; no live inference |
| 65/116 controls deferred | By design | No truthful backend exists |
| 7 controls disabled in catalogue | By design | Explicitly marked unavailable |
| 21/116 CONTROL_CATALOG rows malformed | Upstream | Heuristic screen mapping |
| Traffic Manager WRITE_ONLY | CARLA 0.9.16 limitation | No getter exists; restore impossible |
| GAP-026 geometry thresholds | Unresolved | No wired threshold; not shown as PASS |
| Geometry continuity | INCONCLUSIVE | No owner-approved tolerance |
| Q12 non-waivable gate taxonomy | Undecided | Waiver can convert identity/integrity FAIL |
| Q22 isolated server lease | Unavailable | Live fuzzing blocked |
| Q9 coordinate-frame branch | Undecided | Calibration semantics may shift |
| Q10/Q11 sensor timestamps/drift | No measurement | Controls stay NOT MEASURED |
| Q23 calibration threshold owner | Unassigned | Validation status never advances |
| No contrast/AT measurement | Not performed | Only accessible names and focus order |
| No live CARLA run | By design | Full repo suite unrunnable in minimal venv |

---

## Support

- **Issues:** Report at repository issue tracker
- **Logs:** Application logs to audit journal (append-only JSONL)
- **Evidence export:** All screens support redaction-safe export
- **Rollback:** Preferences backup created on every write; restore from `.bak` file

---

*This documentation corresponds to source SHA `c69b60d2fe4ac018136ea0fa26e435a09c15dd73`
on branch `integration/carla-gui-integration-20261015`.*