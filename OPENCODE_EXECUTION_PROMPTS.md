# OpenCode Execution Prompts

Ready-to-send prompts for mechanical production engineering: wiring already-built-but-unused modules
into the live pipeline, deprecation migration, documentation housekeeping, evidence-file corrections.
OpenCode does not implement new algorithms — that's Codex's job (see `CODEX_EXECUTION_PROMPTS.md`).

## The one rule that matters most for this whole document

**Every deprecation-migration decision must classify the candidate file as exactly one of three
things before touching it — this is not optional, and getting it wrong is worse than doing nothing:**

1. **DEPRECATE** — genuinely superseded. A live, current implementation exists elsewhere, the
   candidate is provably unreferenced anywhere in the live codebase, moving it changes no behavior.
2. **UNWIRED_BUT_NEEDED** — real, tested, working code that simply isn't called from the live
   pipeline yet. **Never deprecate this.** Wire it in instead.
3. **UNCERTAIN** — cannot confidently classify either way. Do not move it. Escalate to Claude or the
   operator instead of guessing.

If you are not sure which bucket a file belongs in, it belongs in bucket 3, not bucket 1. A
false-positive deprecation (archiving something still needed) is a much worse outcome than leaving a
genuinely dead file in place a little longer.

---

## PROMPT 1 — Wire `check_junction_connection_coverage.py` into acceptance gates (GAP-012, UNWIRED_BUT_NEEDED)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/wire-junction-coverage-<date>.

This module (ultimate_pipeline/quality/check_junction_connection_coverage.py) is real, working, and
tested -- it implements genuine geometry+heading-aware CONFIDENT/AMBIGUOUS/NO_CANDIDATE
classification for a real defect class (a road pointing at a junction that the junction's own
connection list doesn't cite back). Confirmed via repo-wide import search: it is imported nowhere
outside its own test file. This is a "wire it in" task, not a "why does this exist" question -- the
module's own docstring already documents it as explicitly read-only/diagnostic-safe.

TASK: call this module from scripts/measure_candidate_acceptance.py::run_gates() (the same place
JunctionIntegrityGate is already called), and surface its output in
ultimate_pipeline/quality/map_acceptance.py's report. Wire it as ADVISORY/non-hard-fail initially --
its historical pass/fail rate against the current map-of-record hasn't been characterized yet, so
making it a hard-fail gate on day one could block legitimate promotions on an uncharacterized signal.
Run it against the current pinned map-of-record and report exactly what it finds (counts by
CONFIDENT/AMBIGUOUS/NO_CANDIDATE).

This is a small, purely additive change -- do not modify the module's own logic, only its wiring.

End with:
WIRED: PASS | FAIL
PINNED_MAP_FINDINGS: <CONFIDENT count>, <AMBIGUOUS count>, <NO_CANDIDATE count>
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## PROMPT 2 — Retire the superseded `tools/junction_connector_rebuild.py` (GAP — DEPRECATE, confirmed)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/deprecate-old-connector-tool-<date>.

CLASSIFICATION: DEPRECATE. Evidence required before you touch anything (do this first, and paste the
actual command output into your commit message, not a restated claim):

1. Confirm ultimate_pipeline/topology/junction_connector_rebuild.py (NOT the tools/ one) is the
   version actually called from ultimate_pipeline/pipeline_stages/stage_05_geometry.py:
     grep -n "junction_connector_rebuild" ultimate_pipeline/pipeline_stages/stage_05_geometry.py
   Confirm it imports from `topology`, not `tools`.

2. Confirm ultimate_pipeline/tools/junction_connector_rebuild.py is not imported anywhere else in the
   live codebase:
     grep -rln "tools.junction_connector_rebuild\|tools import junction_connector_rebuild" \
       ultimate_pipeline/ tools/ scripts/ tests/
   (excluding the file's own directory and its own test file, if it has one -- check whether it has a
   dedicated test file first; if it does, that test file moves WITH it, not left orphaned)

3. Confirm no CLI entrypoint or script invokes tools/junction_connector_rebuild.py directly (check for
   an `if __name__ == "__main__":` block and whether anything in scripts/ or docs/ references running
   it as a standalone script -- if it IS a real, intentionally-standalone CLI tool rather than a dead
   duplicate implementation, STOP and reclassify as UNCERTAIN, do not deprecate a working CLI tool
   just because its underlying logic overlaps with a pipeline-internal module).

If all three confirm DEPRECATE: move the file (and its test file, if any) to a `deprecated/` location
mirroring the existing docs/deprecated/ pattern already established in DOCS_INFORMATION_ARCHITECTURE.md
(create ultimate_pipeline/deprecated/ if it doesn't exist, or use whatever convention Claude's docs
information architecture already specifies -- check that document first). Add a one-line pointer at
the OLD location's former path is not needed (git history preserves it), but DO add a note in
deprecated/README.md (create if missing) recording: what it was, why it was deprecated, what
supersedes it, and the date/evidence.

If ANY of the three checks are inconclusive: STOP, do not move the file, report UNCERTAIN with your
specific evidence gap to Claude.

End with:
CLASSIFICATION_CONFIRMED: DEPRECATE | UNCERTAIN (stopped, did not move)
EVIDENCE: <paste the actual grep outputs>
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## PROMPT 3 — Documentation deprecation migration (per `DOCS_INFORMATION_ARCHITECTURE.md`)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/docs-deprecation-migration-<date>.

Read DOCS_INFORMATION_ARCHITECTURE.md on this branch (architecture/production-map-quality-20260906)
first -- it already identifies the reconciled target structure and explicitly marks which moves are
authorized for this pass vs. deferred.

AUTHORIZED for this pass (already explicitly classified as historical handoff packets, safe to move):
  docs/02_CLAUDE_C0_REVIEW_PROMPT.md
  docs/N04_CLAUDE_C0_PACKET.md
  docs/N19_CLAUDE_C1_PACKET.md
  docs/R05_CARLA_0916_CROSSWALK_OBJECT_SCHEMA.md
Move these to docs/deprecated/, create docs/deprecated/README.md and docs/deprecated/MANIFEST.yaml
(schema: your choice, but must record original path, move date, and a one-line reason per entry) per
the target structure that document proposes.

NOT authorized for this pass -- do not move these even though DOCS_INFORMATION_ARCHITECTURE.md
discusses them, because they are real, current, actively-referenced documentation, not deprecation
candidates:
  docs/ARCHITECTURE.md, docs/REPOSITORY_GOVERNANCE.md, docs/REPRODUCIBILITY.md, docs/REPO_HEALTH.md,
  docs/KNOWN_LIMITATIONS.md, everything under docs/research/, docs/runtime/, docs/hardening/,
  docs/remediation/, docs/submission/
These are candidates for a future RENAME/reorganize-in-place pass (moving docs/ARCHITECTURE.md to
docs/architecture/overview.md, for example) -- that is a different, larger operation than deprecation
and is explicitly out of scope for this prompt. Do not do it as a side effect of this pass.

Update docs/index.md's links if any of the 4 moved files were referenced there (check first; per this
session's own docs/index.md they should not be, but verify).

End with:
FILES_MOVED: <list>
FILES_LEFT_IN_PLACE: <confirm you did NOT move anything from the "not authorized" list>
MANIFEST_CREATED: PASS | FAIL
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## PROMPT 4 — z-fighting detector (GAP-027)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/z-fighting-detector-<date>.
Prerequisite: run this only after Codex's Wave 4 Phase-J wiring work (GAP-013) lands, since it's more
useful to test against a full-scale run than the current 19-vertex smoke fixture -- check whether
that's landed yet; if not, this can still be built and unit-tested standalone, just note in your
report that full-scale validation is pending.

CONFIRMED (this session's audit): zero hits anywhere in the codebase for "z-fighting"/"z_fighting" --
no existing detector for this defect class. ultimate_pipeline/enrichment/detached_slab_check.py (part
of the Phase J tooling) already has a `duplicate_faces_check` and `floating_slab_check` -- extend this
module rather than creating a new one, following its existing patterns (near-coplanar overlapping
triangle detection with edge-sharing exclusion is the closest existing building block).

TASK: add a check flagging near-coplanar, near-overlapping mesh surfaces at sub-mm/cm separation
(the classic z-fighting signature) as a new sub-check within detached_slab_check.py or a clearly
paired sibling module. Build a synthetic test fixture with two deliberately near-coplanar overlapping
meshes to prove the detector fires, plus a fixture with clearly-separated meshes to prove it doesn't
false-positive.

End with:
DETECTOR_ADDED: PASS | FAIL
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## PROMPT 5 — Stale comment fixes (GAP-028, GAP-029)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/stale-comment-fixes-<date>.
Two trivial, independent documentation-accuracy fixes:

1. GAP-028: ultimate_pipeline/quality/check_junction_connection_coverage.py's own comment implies
   roundabout junctions are excluded from its analysis because they're "wholesale-rewritten
   elsewhere" -- but roundabout reconstruction is confirmed OFF by default in every named release
   profile (grep settings.py for ENABLE_ROUNDABOUT_RECONSTRUCTION to re-confirm this is still true
   before editing). Correct the comment to state the actual current behavior.

2. GAP-029: document the two properly-gated, narrow Ingolstadt-specific hardcodes in
   ultimate_pipeline/enrichment/elevation_importer.py (the 375.0m elevation fallback, reachable only
   in explicit lenient-mode; the UTM-zone-32 fallback, reachable only on a near-unreachable malformed
   geoReference input) with clear inline comments explaining their narrow scope, if not already
   present. Do not remove either hardcode -- both are legitimate last-resort fallbacks, this is a
   documentation clarity fix only.

End with:
GAP-028: PASS | FAIL
GAP-029: PASS | FAIL
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## What NOT to do, ever, without separate explicit authorization

- Do not touch anything under `submission/` for any reason.
- Do not touch `campaigns/`, `reports/post_audit_hardening/` (read-only, historical, append-only per
  `REPOSITORY_GOVERNANCE.md`).
- Do not touch `ultimate_pipeline/carla_tools/map_registry.py` (the map-of-record pin).
- Do not delete a worktree or branch without being asked.
- Do not merge any branch yourself — Claude reviews, the operator merges.
- Do not treat "the docs information architecture document mentions this file" as authorization to
  move it — only the explicit "AUTHORIZED for this pass" list in Prompt 3 above is authorized.
