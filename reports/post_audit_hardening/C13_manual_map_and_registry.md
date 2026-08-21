# C13 (HIGH) — Manual map (Grid0828) acceptance + content-addressed registry (pin the pair)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: `fix/post-audit-phase-e-junctions-roundabouts-20260803` (HEAD `559888b4`+) · Interp: `./.venv/Scripts/python.exe` · UP_DISABLE_CARLA=1 for offline parts
Rules: TDD for code; full-suite green; **EXPLICIT-PATHSPEC commit**; map-touching → human review. Model: Codex/Sonnet high.
Plan: `~/.claude/plans/velvet-wobbling-lighthouse.md` (Phase R1). Depends on R0 (pinned auto map).

## Why
RQ1 (structural gap) and RQ2 (perceptual gap) both need the **auto↔manual pair pinned by digest**. The auto map
is pinned by R0/C12. This task brings the **manual Grid0828** side to parity and pins BOTH in one content-addressed
registry, so every downstream RQ references maps by sha256, not by mutable name. Memory notes a Grid0821/0828
**name↔content drift** ([[project_map_safety_untracked_20260730]], Grid0828 runbook) that must be resolved here.

## Inputs (verified present)
- Manual XODR: `E:/CARLA/CARLA_0.9.16/CarlaUE4/Content/Grid0828/Maps/Grid0828/OpenDrive/Grid0828.xodr`
  (993 roads, 119 junctions, geoReference UTM-32N `+lon_0=9 +k=0.9996 +x_0=500000`). Grid0821 alongside.
- Corrected acceptance: `ultimate_pipeline/quality/map_acceptance.py`; registry: `carla_tools/map_registry.py`
  (already resolves Grid0828 identity); manifest discipline: `campaigns/.../source/INPUTS_MANIFEST.json` +
  `governance/inputs_manifest.py`.

## Steps
1. **Pin the manual XODR as a tracked input.** Copy Grid0828.xodr (and Grid0821 if the protocol needs both —
   `protocol.py` REQUIRED_MANUAL_MAPS = {Grid0821, Grid0828}) into
   `campaigns/ingolstadt_cooked_perception_v1/source/manual/`; record sha256+bytes in a manifest entry
   (`source_manual_grid0828`) via `governance.inputs_manifest` (same fail-closed guard as roads/DEM/buildings).
2. **Run corrected acceptance on the manual map** (offline where possible):
   `python scripts/measure_candidate_acceptance.py <Grid0828.xodr>` → `map_acceptance.build_map_acceptance(...)`.
   NB the manual map is HAND-MODELED: it will differ from the auto map (its own enrichment/signals/lane
   conventions). Do NOT force `require_enrichment=True` on it the same way as the auto map — accept the manual map
   on the CARLA-fatal invariants (geometric continuity via the C6-corrected checker, lane-successor connectivity,
   G19 at 1e-9, schema, origin_sanity). Record its gate results as-is; a hand-modeled map is the *reference*, not a
   pipeline output.
3. **Crash-safe repair ONLY if it fails a CARLA-fatal gate** (e.g. missing lane successors) — reuse
   `tools/crash_safe_length_repair.py` / the C10 hygiene + lane-successor autofix; human review; keep the original
   as the provenance parent. If it passes, do nothing.
4. **Content-addressed registry pins BOTH maps.** Extend `carla_tools/map_registry.py` (or a small
   `registry.json` under `campaigns/.../`) to map: canonical name → {xodr path, sha256, frame, role(auto|manual),
   acceptance verdict}. Resolve the Grid0821/0828 name↔content drift (assert the sha256 of the file each name
   resolves to; fail-closed on a name pointing at unexpected content). TDD the drift guard (a name→wrong-sha must
   fail).
5. **Loadability (server-gated, if CARLA up):** confirm each pinned map loads in CARLA and reports the expected
   world identity (`map_registry` identity resolution + `tools/map_only_probe.py`); else mark loadability DEFERRED.

## Boundaries
- Do not "improve" the hand-modeled manual map beyond CARLA-fatal crash-safety — it is the reference arm; altering
  its geometry/semantics would contaminate the RQ1/RQ2 comparison. Deterministic/offline for tests.
- Fail-closed: a registry name resolving to unexpected sha256 must raise; no silent name↔content drift.

## Deliverables / verdict
- `source/manual/Grid0828.xodr` (+Grid0821) pinned + manifest entries; registry pinning BOTH maps by sha256;
  drift guard + tests (`tests/unit/test_map_registry_pinning.py`).
- `reports/post_audit_hardening/C13_MANUAL_MAP_AND_REGISTRY.md`: both maps' sha256 + acceptance results + the
  resolved name↔content drift.
- Push (explicit pathspec); local==remote; full suite green.
- **Verdict:** `PAIR_PINNED auto=<sha> manual=<sha> loadable=<PASS|DEFERRED> drift=RESOLVED` | PARTIAL | BLOCKED.

---

## Closure (2026-08-21, Sonnet) — step 4, the registry + drift guard

Steps 1-3 were already done (commit `fd6951c7`): manual XODR pinned, acceptance run, C14's structural
comparator implemented. Step 4 (the content-addressed registry itself + its TDD drift guard) was still
open — this closes it.

`ultimate_pipeline/carla_tools/map_registry.py` gets a new, separate content-addressed section
(`PINNED_MAP_REGISTRY` + `verify_pinned_map()`), distinct from the existing map-*name*-normalization
registry already in that file. `verify_pinned_map(name)` resolves any registered alias (`"Grid0828"`,
`"Grid0821"`, `"auto_map_of_record"`, `"map_of_record"`, ...) to its pinned entry, then fails closed
(`MapRegistryDriftError`) if the file is missing, is an un-smudged git-LFS pointer stub (distinct,
actionable message — not a confusing hash mismatch), or its on-disk sha256 doesn't match the pin.

Both real pins independently re-verified (sha256 recomputed directly from disk, not taken from any
report/commit-message text):
- auto: `69b1f52016ebdc3e643616f86161d85789624c94d48e5caf56c53004d534de6e`
- manual: `5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c`
- `Grid0821` resolves to the same content as `Grid0828`, as `MANUAL_MANIFEST.json` already documented.

**Tests:** `tests/unit/test_map_registry_pinning.py` (10 tests) — positive/negative controls on
synthetic fixtures (the TDD-mandated "a name→wrong-sha must fail" case), missing-file guard,
unregistered-name guard, alias resolution, LFS-pointer detection, plus 4 integration-style checks
against the real repo pins.

Full offline suite: 3006 passed, 78 skipped, 0 failed (one `test_writer_lock.py` timing flake,
confirmed unrelated — passes standalone).

Loadability (step 5) is **DEFERRED**: CARLA is currently occupied by concurrent GPU-diagnostic work
on this machine (C20), not attempted here to avoid interfering with that live probe.

**Updated verdict:** `PAIR_PINNED auto=69b1f520 manual=5eaece23 loadable=DEFERRED drift=RESOLVED`
