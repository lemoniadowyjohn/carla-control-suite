# SONNET C12 (HIGH) — Regenerate the map of record from the corrected pipeline → pin → live-CARLA drivability

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: `fix/post-audit-phase-e-junctions-roundabouts-20260803` @ `87d868ca` (C6–C11 landed, 2937 tests pass)
Interp: `./.venv/Scripts/python.exe` · SUMO required for Stage A · CARLA (E:/CARLA/CARLA_0.9.16) for Stage B
Rules: TDD for any code fix; **EXPLICIT-PATHSPEC commit**; map-of-record pin = human review. This is the culmination — do NOT re-open C6–C11.

## Context — everything upstream is done; produce + verify THE map of record
The corrected pipeline is merged and the canonical entrypoint **already exists and is complete**:
`scripts/regen_map_of_record.py` (verifies pinned-input digests fail-closed → Osm2Odr seed → corrected pipeline
[hygiene on, preanchor off, autofix lane successors, OSM_FILE wired] → rebase-to-local for CARLA float32 safety →
acceptance with `require_enrichment=True` → emits a candidate ONLY if acceptance passes).
Pinned inputs (`campaigns/.../source/INPUTS_MANIFEST.json`): roads `b9e07465`, DEM `3cfa665d`, buildings `92300f0a` (5692).
No fresh candidate has been produced from the fully-corrected code + acceptance-gated yet. That's this task.

## Stage A — Regenerate + acceptance (offline; needs SUMO)
1. Ensure SUMO is resolvable (the script checks `SUMO_HOME` / PATH / `Settings.SUMO_NETCONVERT`).
2. Run the canonical command (long; capture the log):
   ```
   python scripts/regen_map_of_record.py
   ```
   It refuses on a dirty worktree (`--allow-dirty` only if you must) and emits a candidate ONLY if
   `map_acceptance.valid_for_experiments == True`.
3. If it **fails a gate**, it fails closed with the reason. Diagnose against the corrected gates (they now measure
   reality — a failure here is likely a REAL defect, not checker noise). Fix via TDD if it's a genuine pipeline bug
   (map-touching → human review), or report the precise blocker. Do NOT loosen a gate to force a pass.
4. On success, record from `regen_provenance.json`: the OSM→seed→final→emitted sha chain, and the acceptance
   metrics (expect: continuity true=0, lane successors 0 missing, islands quarantined, **buildings ≈5692**,
   **functional `<signal>` ≈60**, real elevation band ~360–413 m, G19=0 at 1e-9).

## Stage B — Pin the map of record (governance: human review)
5. Only if Stage A acceptance PASSES: pin the emitted candidate as the auto map-of-record.
   - Record its sha256 in the content-addressed registry / evidence
     (`reports/post_audit_hardening/<ts>_C12_MAP_OF_RECORD/`).
   - This is the FIRST legitimately pin-eligible candidate (continuity, enrichment, hygiene, reproducibility all
     satisfied). Update memory [[project_c0_clean_regen_pinned]] to PINNED with the new sha + provenance
     (supersedes the retracted `471bea48` and the diagnostic `83418373`).
   - Present the sha + acceptance summary for human sign-off before declaring it authoritative.

## Stage C — Live-CARLA drivability (server-gated; first real "drivable" proof)
6. With a running CARLA 0.9.16 server (mind the streaming-port failure mode — see [[project_carla_runtime]]):
   - Load the pinned XODR (OpenDRIVE-standalone `generate_opendrive_world`, or the cooked path if available).
   - Reuse the existing probes: `scripts/find_carla_server.py`, `scripts/client_waypoint_probe.py`,
     `scripts/drive_route_probe.py`.
   - Confirm: loads without crash; a spawned ego navigates a route; the rebase-to-local frame keeps float32
     precision acceptable (origin_sanity already passed offline).
7. Record the drive result. If the server is unavailable, mark Stage C `DEFERRED` (Stages A+B still stand).

## Boundaries
- Use the corrected pipeline + existing entrypoint AS-IS; don't rebuild them. Don't re-fix C6–C11.
- Never emit/pin a candidate that fails acceptance. Live-CARLA is the only server-dependent step.

## Deliverables / verdict
- `regen_provenance.json` + `map_acceptance.json` (Stage A), pinned candidate + registry entry (Stage B),
  drive-probe report (Stage C), updated memory.
- Push (explicit pathspec); local==remote.
- **Verdict:** `MAP_OF_RECORD_PINNED sha256=<...> acceptance=PASS drivable=<PASS|DEFERRED>` | REGEN_FAILED_AT_GATE=<gate> | BLOCKED.
