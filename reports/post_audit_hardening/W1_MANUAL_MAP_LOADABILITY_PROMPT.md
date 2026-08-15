# CODEX W1 - Manual-map loadability and crash-safety verification

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803
Interpreter: ./.venv/Scripts/python.exe
Environment: always set UP_DISABLE_CARLA=1 for offline tests
Model: Codex 5.x high for repair, mid/high for verification only

## Why

The auto-map crash-safety and loadability chain is now strong: E1/E1B/E2 produced an elevated,
crash-safe, offline-loadable candidate. The manual-reference side of the thesis comparison has not received the
same treatment. Current branch searches do not show the Grid0821/Grid0828 manual XODR artifacts in the canonical
tree; they appear to live in sibling worktrees or submission mirrors. RQ1 and the perceptual comparison both depend
on a manual map that is content-pinned and loadable.

This is a real comparison-validity gap: if the manual map has G19 length-invariant, strict preflight, or CARLA
loadability defects, the auto-vs-manual comparison is not symmetric.

## Goal

Produce a fail-closed W1 evidence bundle answering:

- Which manual map is the canonical RQ1 reference?
- Where is it, and what is its full sha256?
- What is its content signature: road, junction, signal, object, elevation counts?
- Does it pass offline G19 length-invariant evidence?
- Does it pass strict XODR loadability preflight?
- If it fails, is a repaired manual candidate needed before B4/RQ1 can run?

If repair is required, produce a new repaired manual candidate without overwriting or committing the immutable
manual parent.

## Absolute Boundaries

- Do not mutate or overwrite any parent manual XODR.
- Do not commit large `.xodr` artifacts.
- Do not change certifier or gate logic.
- Do not fabricate evidence or mark manual loadability as pass without real checks.
- Do not silently use Grid0821 when Grid0828 is requested, or vice versa.
- No CARLA in offline tests. Live CARLA load smoke is a separate runtime step after W1 offline evidence.

## Step-by-step

1. Discover manual candidates.
   - Search the current repo and sibling worktrees for Grid0821/Grid0828/manual Ingolstadt XODRs.
   - Record path, full sha256, file size, and basic content signature.
   - If no manual XODR is available to this workspace, stop with `BLOCKED_MANUAL_MAP_MISSING`.

2. Pin the reference.
   - Reuse or extend `ultimate_pipeline/carla_tools/map_registry.py` as planned by B3.
   - Register `GRID0821`, `GRID0828`, and the auto Ingolstadt reference by full sha256 plus content signature.
   - Reject name/content mismatch, especially Grid0828-named files whose counts match Grid0821 content.
   - If the canonical manual reference is ambiguous, stop with `BLOCKED_NEEDS_DECISION` and list candidates.

3. Run offline safety checks on the pinned manual parent.
   - G19 length-invariant diagnostic/evidence.
   - `tools/preflight_xodr_loadability.py`.
   - strict XODR validator / schema validator already used in E1/E2.
   - Count roads, junctions, signals, objects, elevation records, and nonpositive geometry.

4. Decide.
   - If G19 violations = 0 and preflight hard errors = 0, report `MANUAL_REF_LOADABLE_OFFLINE`.
   - If failures exist, report exact failing road IDs / geometry IDs and continue only if repair is mechanically
     equivalent to existing E1/E1B/E2 repair classes.
   - If the failure class is new or ambiguous, stop with `BLOCKED_NEEDS_DECISION`.

5. Repair only if required.
   - For G19 length overflow, reuse the E1 `crash_safe_length_repair` method.
   - For zero/nonpositive geometry stubs, reuse the E1B `zero_length_connector_repair` method.
   - Preserve road, junction, signal, object, elevation, and semantic counts unless the report explicitly proves
     that a count-preserving repair is impossible.
   - Write a new ignored artifact such as
     `campaigns/ingolstadt_cooked_perception_v1/manual/ingolstadt_manual_loadable_safe.xodr`.
   - Do not commit the repaired XODR; record its full sha256.

6. Verify repaired output if created.
   - G19 violations = 0.
   - strict preflight hard errors = 0.
   - schema valid.
   - content signature preserved or documented.
   - full offline suite green.

## Tests

Add offline synthetic tests under `tests/unit/`:

- registry rejects name/content mismatch;
- registry resolves manual map by full sha256;
- manual safety summary fails closed when the manual artifact is missing;
- repair path preserves counts on a tiny synthetic violating manual XODR, if a repair helper is added.

## Deliverables

- `reports/post_audit_hardening/W1_MANUAL_MAP_LOADABILITY.md`
- `reports/post_audit_hardening/W1_MANUAL_MAP_LOADABILITY.json`
- registry/test changes if needed
- repaired manual candidate sha256 if created, not committed
- full-suite pytest summary

## Commit Discipline

Use an explicit commit pathspec. Do not commit any `.xodr` artifact, scratch log, or unrelated staged file.

Example:

```powershell
git commit -m "test(manual-map): pin and verify manual loadability" -- <explicit W1 files>
```

## Verdict

`MANUAL_REF_LOADABLE_OFFLINE | MANUAL_REF_REPAIRED_OFFLINE | BLOCKED_MANUAL_MAP_MISSING | BLOCKED_NEEDS_DECISION`

## Out of Scope

- Live CARLA load smoke of the manual map.
- Unreal cooking.
- RQ1 auto-vs-manual result generation, which remains B4 after the manual reference is pinned and loadable.
