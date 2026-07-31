# DSV05 — New-XODR Read-Only Structural Summary (pre-C55V01b)

**Model:** DeepSeek V4 Light · **Mode:** READ-ONLY (existing tools only; no new logic, no repair) · **Task ID:** DSV03-06-REPORTS
**Target:** `campaigns/ingolstadt_cooked_perception_v1/candidate/raw_xodr_run_1_epsg32632_header_pinned.xodr` (LFS oid `ff2a05e7…`, 82,318,919 B)
**Verdict:** `STRUCTURAL_SUMMARY_CAPTURED`

## 1. Tools used (existing, read-only — verified no file writes)

| Tool | Path | Notes |
|---|---|---|
| `check_post_tiling_integrity.py` (primary) | `carla_main_governed_worktrees/codex-jsnap-20260428/ultimate_pipeline/quality/check_post_tiling_integrity.py` | `ET.parse` + stdout JSON only; no `--out`; run with defaults `--eps-xy 0.05 --eps-hdg 0.01` via `.venv` Python 3.12.2; succeeded |
| `check_lane_link_targets_exist.py` (supplement) | same worktree, `ultimate_pipeline/quality/check_lane_link_targets_exist.py` | `--xodr` only, no `--out`; succeeded |
| `elevation_summary.py` | codex-jsnap copy broken (missing `core.odr_io`); governed copy runs but is DEM-guidance only, emits no XODR elevation records | — |

## 2. Counts

| Metric | Value | Source |
|---|---|---|
| roads | **32,710** | tool `num_roads` |
| junctions | **3,646** | tool `num_junctions` |
| signals | **0** | tool `num_signals` |
| connections | not provided by tool (junction-connector tools are mutating → disqualified) | — |
| LaneLinks | not provided (no read-only counter); **0 dangling laneLink targets** | `check_lane_link_targets_exist` |
| elevation records | not provided by tool; vertical profile recorded `LOCAL_FLAT_ZERO_NO_DEM` in candidate manifest (flat z=0 by decision — expected, not a defect) | manifest |
| primitive types (line/arc/spiral/poly3/paramPoly3) | not provided by tool | — |
| road-link coverage % | not provided by tool | — |

## 3. Mechanical issue counts (counts only — NO validity verdict; Codex 5.5 owns the gate)

| Issue class | Count |
|---|---|
| duplicate road/junction/signal IDs | 0 |
| dangling junction refs (missing incoming/connecting road) | 0 |
| orphan road links (pred/succ → missing road) | 0 |
| dangling laneLink targets | 0 |
| seam_endpoint_issues (link endpoint mismatch > 0.05 m / 0.01 rad) | **27,645** |
| warnings | 0 |
| tool `ok` | `false` (exit 2) — informational; verdict deferred per fence |

## 4. Vertical note

LOCAL_FLAT_ZERO by decision (z=0 flat expected; DEM-free). No defect flag.

## 5. Handoff note for C55V01b

Structural identity vs raw run 1: `semantic_sha256` `019fc30e…` shared by run_1/pinned/run_2 (header-pin only). The 27,645 seam-endpoint findings are the highest-signal mechanical item for Codex's structural-freeze review.
