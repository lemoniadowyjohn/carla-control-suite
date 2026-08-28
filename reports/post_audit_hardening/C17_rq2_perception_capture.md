# C17 (HIGH) — RQ2: paired perception capture (fair, same rig)  *(CARLA ✅; path B cook-gated)*

Repo/branch/interp as C13. Plan: Phase R5. Depends on C12+C13 (pinned pair). CARLA server available.

## RQ2
*What are the perceptual differences between the auto and manual maps as seen by the sensor rig?*

## Two paths (both honest — see plan)
- **Path A — OpenDRIVE-standalone, both maps (NOW):** load pinned auto XODR AND Grid0828 XODR via
  `carla.Client.generate_opendrive_world(...)` at identical fidelity → capture same route. Measures STRUCTURE-driven
  perceptual gap only → classify `BOUNDED`, never `PAIRED_INGOLSTADT`.
- **Path B — cooked maps (DEFERRED, C16):** → `PAIRED_INGOLSTADT` incl. assets/textures.

## Steps (Path A, actionable now)
1. **Same rig, same assets, both maps** (fair-capture / D5): `carla_tools/thesis_sensor_rig.py` — K_undistortion
   pinhole cameras (ignore K/D), `image_size` W×H, cTv direct (vehicle→camera), LiDAR vTl inverted (LiDAR→Vehicle).
   Protocol route + `fps=20`/`fixed_delta=0.05` from `experiments/thesis/protocol.yaml`.
2. **Capture via the C8-corrected writer** `perception/capture_writer.py` → `rgb/<cam>/` + `semseg_raw/<cam>/`
   (RAW class ids, no palette). **Confirm LiDAR is captured** in the canonical path (audit gap #12: the generators
   previously captured only cameras) — add semantic-LiDAR capture if missing (TDD). Handle `Any=255` → ignore_index.
3. **Classify** each arm + the pair (`config/thesis_contract.py::classify_pair_perception_result`) → expect
   `BOUNDED` (structure-only, both arms standalone). Write `perception_status.json` + `visual_qa_contract.json`
   (`build_visual_qa_contract`: world_loaded, correct_world_identity, ego_spawned, sensors_attached, first_frame,
   evidence_written) — verify world identity via `carla_tools/map_registry.py` + `tools/map_only_probe.py`.
4. **RQ2 perceptual gap** on the paired captures: `domain_gap/perception_gap.py`, `tile_perception_gap.py`.

## Boundaries / verdict
- Same rig+assets+route+weather on BOTH arms (fairness). Never label a standalone capture `PAIRED_INGOLSTADT`.
- Verdict: `RQ2_PERCEPTUAL_GAP path=A class=BOUNDED gap=<x> lidar=<captured|added>` (now); path B → later.
