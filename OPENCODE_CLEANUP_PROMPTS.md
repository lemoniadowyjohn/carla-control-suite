# OpenCode — comprehensive repo cleanup / deprecation-migration prompts

All 3 prompts below are based on a full repo survey completed 2026-09-07 (root files, root
scripts, all `reports/` top-level subdirectories except the frozen `post_audit_hardening/`, and
all top-level directories). Every claim below was independently verified (grep for live
references) before being included — do not re-derive from scratch, but DO re-confirm immediately
before acting, since time has passed and this is a Windows repo where `git mv` needs care.

## The one rule that matters most (repeat from earlier prompts, still applies)

**Classify every candidate as exactly one of: DEPRECATE / UNWIRED_BUT_NEEDED / UNCERTAIN before
touching it.** A false-positive deprecation (archiving something still needed) is worse than
leaving a genuinely dead file in place. If unsure, it's UNCERTAIN — escalate, don't move.

This repo also has its own, more detailed 8-category scheme already defined in
`docs/deprecated/README.md`/`MANIFEST.yaml`: `CURRENT_AUTHORITY`, `ACTIVE_RUNTIME`,
`ACTIVE_RESEARCH`, `FROZEN_EVIDENCE`, `HISTORICAL_AUDIT`, `DEPRECATED`, `GENERATED`, `UNCERTAIN`.
Use THAT scheme for the actual MANIFEST.yaml entries (it's more precise); use the 3-bucket rule
above as your gut-check before acting.

## Absolute exclusions — confirmed LIVE, do not move/touch/delete, for any of the 3 prompts below

- `AGENT_TASK_LEDGER.md`, `agent_sync.yaml` (repo root) — heavily validated by
  `ultimate_pipeline/tools/validate_governance.py`, `ultimate_pipeline/contracts/agent_sync.py`,
  `tests/unit/test_agent_sync_contract.py` (which asserts `agent_sync.yaml` must exist at repo
  root). CURRENT_AUTHORITY / ACTIVE_RUNTIME.
- `reports/architecture_gate/AG04_coordinate_contract.json` — read directly by
  `ultimate_pipeline/contracts/coordinate_contract.py` (`AG04_RELATIVE` constant) and
  `ultimate_pipeline/tools/j5r_visual_asset_transform_chain.py:30`, exercised by
  `ultimate_pipeline/tests/unit/test_coordinate_contract.py`. The REST of
  `reports/architecture_gate/` (AG01-03, AG05-07) may be historical -- verify each individually,
  do not assume the whole directory is safe just because AG04 is excluded.
- `reports/visual_structural_reconciliation/C44V01_coordinate_contract.json`,
  `C44V01_coordinate_contract.md`, `C44V01_alignment_results.json` — same `coordinate_contract.py`
  module (`COORDINATE_REPORT_RELATIVE`, `ALIGNMENT_REPORT_RELATIVE`, `MARKDOWN_REPORT_RELATIVE`),
  same test file. The rest of that directory (00-05 worktree/lineage docs) may be historical --
  verify individually.
- `reports/repo_health/` (entire directory) — `ultimate_pipeline/cli.py:248` defaults
  `--out-dir` to `reports/repo_health/latest`. This is active output space (most recent mtime of
  any reports/ subdirectory, 2026-09-06), not historical evidence.
- `run_n_certify.py`, `stage_0_provenance.py` (repo root) — imported by
  `tests/unit/test_opendrive_gen_diagnostic.py` and `ultimate_pipeline/tests/test_stage_d0.py`
  respectively. The other 25 files in the same "post_audit_hardening campaign driver" cluster
  (stage_c1_generation.py, stage_c2*.py, etc.) are interlocking with these two and with each
  other -- DO NOT touch any file in this cluster in this pass; it needs its own dedicated,
  carefully-scoped investigation, not a bulk sweep. (Full cluster list is in the survey; if you
  need it, run `ls *.py | grep -v conftest` at repo root and cross-reference imports yourself
  rather than trusting a stale list.)
- `reports/post_audit_hardening/`, `submission/`, `campaigns/` — frozen/append-only per
  `REPOSITORY_GOVERNANCE.md`, already established this session, not re-litigated here.
- `reports/ingolstadt_map_quality_v2/` (397MB) — not inspected in this survey at all. Do not
  touch; flag it back to Claude/the operator as needing its own dedicated look before any
  decision.
- `reports/new_campaign/` — referenced by the untracked root script `generate_audit.py`
  (DSV11-14 paths). Leave in place this pass.
- Anything under `cities/`, `prompts/`, `research/`, `roadrunner_profiles/`, `schemas/` (repo
  root, one level deep) — all have real git-tracked files in them (confirmed via
  `git ls-files <dir> | wc -l` > 0), not clutter. Do not touch without individually
  understanding each file first.

---

## PROMPT 1 — Populate docs/deprecated/ for real (the framework exists, the migration doesn't)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch:
chore/deprecated-layout-<date> (this is the branch name docs/deprecated/README.md already
promises -- "The deprecated migration is executed as a separate task on branch
chore/deprecated-layout-20260906" -- that exact branch/date never existed; create it fresh with
today's date and treat this as fulfilling that promise for real).

CONTEXT: docs/deprecated/README.md and MANIFEST.yaml already define a real classification scheme
(8 categories: CURRENT_AUTHORITY, ACTIVE_RUNTIME, ACTIVE_RESEARCH, FROZEN_EVIDENCE,
HISTORICAL_AUDIT, DEPRECATED, GENERATED, UNCERTAIN) and a 3-subdirectory layout (prompts/,
audits/, remediation/), but MANIFEST.yaml has zero real entries and all 3 subdirectories are
empty -- nothing has actually been migrated yet.

CANDIDATES (verified 2026-09-07, zero live code/doc references found for any of these -- confirm
this is still true with a fresh grep before moving each one, since time has passed):

Root-level, TRACKED, to docs/deprecated/audits/ (classification: HISTORICAL_AUDIT):
  CLAUDE_EVIDENCE_INTEGRITY_AUDIT.json
  CLAUDE_INDEPENDENT_REVIEW.md        (cites CLAUDE_RESEARCH_CLAIM_AUDIT.json internally --
                                        move both together, keep the cross-reference working by
                                        using a relative path from the new location)
  CLAUDE_REPO_HEALTH_AUDIT.json
  CLAUDE_RESEARCH_CLAIM_AUDIT.json
  CLAUDE_RQ_SEMANTIC_AUDIT.json
  (all 5 share identical metadata: head=33d5d815..., branch=stabilize/research-release-20260905,
  generated_at_utc=2026-09-06 -- this is one linked evidence set from a single completed,
  already-superseded independent review, not 5 unrelated files)

  Problems.md (136,995 bytes -- this is the largest single file in this batch; it's a July 2026
  problem register pinned to an uploaded-zip baseline, already known unreliable for the current
  branch)
  ROADRUNNER_MISSING_CAPABILITIES.json
  P03_REPAIR_MUTATION_LEDGER.csv
  P04_REPAIR_MUTATION_SUMMARY.json
  P05_UNEXPECTED_MUTATIONS.csv
  _stage7_acceptance_results.json (small, tracked, no references -- confirm it's genuinely
    tracked with `git ls-files _stage7_acceptance_results.json` before moving)

Root-level, TRACKED, to docs/deprecated/audits/ (classification: GENERATED -- this is a report
ABOUT the current branch's own recently-completed work, not superseded, but also not something
that needs to stay at repo root once its content is captured -- your call whether GENERATED
material belongs in this archive per the README's own rules; if the rules say only
HISTORICAL_AUDIT and proven DEPRECATED get archived, leave this one in place and say so):
  OPENCODE_PRODUCTION_ENGINEERING_REPORT.md (generated 2026-09-07, describes the C0-C16 work
    already committed to this exact branch -- read docs/deprecated/README.md's actual archiving
    rule before deciding to move this one; if it doesn't fit HISTORICAL_AUDIT/DEPRECATED, leave
    it at root)

docs/-level (NOT repo root, one directory down), TRACKED, to docs/deprecated/prompts/
(classification: HISTORICAL_AUDIT -- these are the 4 files an earlier, unmerged branch
(feature/docs-deprecation-migration-20260907) already scoped and moved; that branch never
merged, so redo the same move here for real, superseding the need for that branch to merge
separately):
  docs/02_CLAUDE_C0_REVIEW_PROMPT.md
  docs/N04_CLAUDE_C0_PACKET.md
  docs/N19_CLAUDE_C1_PACKET.md
  docs/R05_CARLA_0916_CROSSWALK_OBJECT_SCHEMA.md
  (docs/02_CLAUDE_C0_REVIEW_PROMPT.md has an internal cross-reference to
  docs/N04_CLAUDE_C0_PACKET.md -- update it to the new relative path when both move together,
  same as the unmerged branch already did correctly)

For EACH file moved: add a real entry to MANIFEST.yaml following its own documented schema
exactly (original_path, deprecated_path, classification, reason, last_known_role, replacement,
referenced_by, historical_commit, moved_in_commit, evidence). Update docs/deprecated/README.md's
"Migration" section to reflect that this branch IS the fulfillment of that forward-reference, not
another dangling promise.

Before moving ANYTHING, re-run this exact check for each candidate file and paste the actual
output into your commit message:
  grep -rn "<filename>" --include="*.py" --include="*.md" --include="*.yaml" --include="*.yml" .
If any candidate now shows a live reference that wasn't there in the 2026-09-07 survey, STOP,
reclassify that one file as UNCERTAIN, and escalate it rather than moving it.

End with:
FILES_MIGRATED: <count>
MANIFEST_ENTRIES_ADDED: <count>
FILES_ESCALATED_AS_UNCERTAIN: <list, or NONE>
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## PROMPT 2 — Retire orphaned old-location docs (superseded by the C0-C16 reorg)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch:
chore/retire-orphaned-docs-<date>.

CONTEXT: the C0-C16 production-engineering pass (already committed on this branch's history,
commit 5577ace2) built a full new docs/ subdirectory structure (docs/architecture/,
docs/governance/, docs/map_quality/, docs/operations/, docs/reference/) with EXPANDED content,
but left the OLD top-level files in place uncleaned. Confirmed 2026-09-07: docs/index.md (the
navigation authority) already links ONLY to the new locations, and no live code references the
old paths. The pairs are NOT identical duplicates -- the new versions are genuine
elaborations/rewrites, not copies -- so do not delete blindly; diff each pair first.

CANDIDATES (verify each with a fresh diff and a fresh grep before acting):
  docs/ARCHITECTURE.md              -- superseded by docs/architecture/overview.md
  docs/REPOSITORY_GOVERNANCE.md     -- superseded by docs/governance/REPOSITORY_GOVERNANCE.md
  docs/REPRODUCIBILITY.md           -- superseded by docs/operations/RUNBOOK.md (verify this is
                                        really the right successor -- REPRODUCIBILITY.md is 12
                                        lines, RUNBOOK.md is 131; confirm RUNBOOK.md actually
                                        covers everything REPRODUCIBILITY.md covered, don't just
                                        assume from file size)
  docs/REPO_HEALTH.md               -- likely superseded by something in docs/operations/ -- you
                                        need to determine the actual successor, it wasn't
                                        conclusively identified in the survey
  docs/KNOWN_LIMITATIONS.md         -- likely candidate for docs/research/ or docs/governance/
                                        per DOCS_INFORMATION_ARCHITECTURE.md's own note ("not
                                        decided here") -- decide it now, either move it into
                                        the new structure for real or confirm it has no
                                        successor and should stay put

For each: (a) diff old vs. new-location content, (b) if the new location is a genuine superset/
elaboration with nothing unique lost, retire the old file to docs/deprecated/ (classification:
DEPRECATED, replacement: <new path>) with a MANIFEST.yaml entry: (c) if the old file has content
NOT present in the new location, do NOT delete it -- either merge the missing content into the
new location first, or leave the old file in place and report it as UNCERTAIN with the specific
missing content named.

Update any remaining internal cross-references (search docs/ and repo-root *.md files for links
to the old paths) to point at the new locations before retiring the old ones.

End with, for each of the 4:
<FILENAME>: RETIRED | KEPT_MISSING_CONTENT | KEPT_NO_SUCCESSOR_FOUND -- <one-line reason>
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## PROMPT 3 — Delete confirmed-dead untracked clutter (no git history to preserve, be direct)

```text
Repository: lemoniadowyjohn/carla-control-suite. This one does NOT need an isolated branch --
none of these files are git-tracked, so there is no git history to preserve and no diff to
review. Still: do this deliberately, and produce a report of exactly what was removed, so it's
auditable even though it's not a commit.

CONTEXT: these files are physically on disk but were ALREADY triaged and gitignored by a prior
cleanup pass (confirmed via `.gitignore` lines ~301-324, a section literally titled
"R13 terminal freeze (S01-classified UNCLASSIFIED / STAGING)" / "Probe / one-off scripts,
transient state"). They were never actually deleted from disk, just excluded from git. This
prompt finishes that prior pass.

DELETE (confirmed gitignored, confirmed zero live references):
  POST_AUDIT_HARDENING_PROMPT.md   (46,362 bytes -- also explicitly classified "LEGACY/STRAY" by
                                     the repo's own classify_untracked() function in
                                     stage_0_provenance.py, asserted by
                                     ultimate_pipeline/tests/test_stage_d0.py:65 -- read that
                                     test before deleting to confirm the test doesn't require the
                                     FILE to exist, only the CLASSIFICATION STRING; if the test
                                     needs the file present, do not delete it, report UNCERTAIN)
  _carla_server.err.log, _carla_server.log
  _p4_run.err.log, _p4_run.log
  _p4_runtime_evidence.json
  _phaseL_run.err.log, _phaseL_run.log
  _stage1_inventory.json
  _stage5_repair_report.json
  submission_files.txt   (61,774 bytes, stale directory-listing dump, dated Aug 3)
  worktree_files.txt     (4,565 bytes, same kind of stale dump)
  texput.log              (LaTeX build byproduct)

DELETE (untracked scratch scripts at repo root, zero external imports found anywhere in the
tree -- re-confirm with `grep -rln "import <name_without_.py>\b" --include="*.py" .` for each
before deleting):
  _a0_gather.py, _p1_repair_audit.py, _stage1_inventory.py, _stage1b_check_geoms.py,
  _stage5_repair.py, _stage7_acceptance.py, _stage7_gate_check.py, _verify_native.py,
  _verify_repair.py, check_raw_run1.py, examine_bad_roads.py
  create_a1_registries.py, generate_audit.py
    (these last 2 hardcode a stale branch name "integration/governed-map-quality-20260729" and
    a stale commit sha -- confirm they are genuinely not run by anything before deleting;
    generate_audit.py is the only script anywhere found to reference reports/new_campaign/ --
    that reports/ directory itself should NOT be touched, only this one dead script that reads
    from it)

DO NOT DELETE (explicitly checked, confirmed load-bearing or ambiguous):
  - _stage7_acceptance_results.json is TRACKED (not untracked) -- this prompt does not cover it,
    see Prompt 1 instead.
  - Anything not on the exact lists above. If you find something that LOOKS like it belongs on
    this list but isn't named here, do not add it yourself -- report it back instead.

End with:
FILES_DELETED: <count>
FILES_KEPT_AFTER_RECHECK: <list with reason, or NONE>
DISK_RECLAIMED_APPROX: <sum of sizes>
```

---

## What this does NOT cover (explicitly out of scope, flagged back to Claude/operator)

- The 27-file "post_audit_hardening campaign driver" script cluster at repo root -- too
  interlocking for a mechanical pass, needs its own dedicated investigation.
- `reports/architecture_gate/`, `reports/visual_structural_reconciliation/` beyond the 4 named
  live-input files -- the REST of each directory may be historical but wasn't individually
  verified.
- `reports/ingolstadt_map_quality_v2/` (397MB) -- not inspected at all yet.
- Large local-disk-only items with no git dimension at all (`venv/` 8.2GB duplicate/wrong-OS
  virtualenv, `work/` 318MB, `carla_governed/` 168MB, `external/` 57MB, etc.) -- these aren't
  git-trackable cleanup, they're local environment housekeeping; the operator is deciding on
  these separately, not part of this OpenCode task.
- Any of the 29 active git worktrees -- separate concern, not part of a documentation/dead-code
  cleanup pass.
