# Merge order / conflict plan — 2026-09-07

Built from a direct file-level and hunk-level analysis of every branch in flight (not assumed —
every claim below was checked with `git diff --name-only` and, where files overlapped, the actual
`@@` hunk ranges). All branches below share a common ancestor at either `2e020d9b` or `f195ba0b`
(`f195ba0b` is a merge of PR #3 into `2e020d9b`, so `2e020d9b` is an ancestor of `f195ba0b` too).

## Correction to something claimed earlier this session

Earlier in this session, the 5 OpenCode branches (P1-P5:
`feature/wire-junction-coverage-20260907`, `feature/deprecate-old-connector-tool-20260907`,
`feature/docs-deprecation-migration-20260907`, `feature/z-fighting-detector-20260907`,
`feature/stale-comment-fixes-20260907`) were described as "genuinely isolated... not stacked on
each other," based on `git merge-base 25849be8 <branch>` all returning `25849be8`. That check was
wrong — it only proves `25849be8` is a common ancestor, not that the branches are siblings.
Checked properly this time (`git merge-base --is-ancestor <A> <B>`): **they are a strict linear
stack.** `feature/stale-comment-fixes-20260907` (P5) contains every commit from P1 through P4 as
direct ancestors. Confirmed via `git log --oneline --graph`.

**Practical consequence: merge P5 only.** It already contains all of P1-P4's work. Merging P1,
P2, P3, and P4 separately (in addition to or instead of P5) would either be redundant or, worse,
produce duplicate/conflicting commits depending on merge order. The 4 earlier branch refs can be
deleted once P5 is confirmed to supersede them (do not delete until a human confirms).

## Group 1 — orthogonal, zero file overlap with anything else, safe in any order

- `chore/production-engineering-20260906` (C0-C16 + the hashing-regression fix, 62 files touched
  vs. base `2e020d9b`: `.env.example`, `.github/workflows/tests.yml`, `pyproject.toml`,
  `tools/validate_thesis_claim_provenance.py`, `ultimate_pipeline/config/settings.py`,
  `ultimate_pipeline/core/run_manifest.py`, `ultimate_pipeline/main_pipeline.py`,
  `ultimate_pipeline/tools/{docs_link_check,release_receipts,repo_health}.py`,
  `ultimate_pipeline/utils/{atomic_io,file_hashing,run_state,structured_log}.py`, plus docs/tests).
  **Zero overlap** with every other branch's touched files, checked directly — the one exception
  is the `docs/deprecated/` collision covered below.
- `feature/roundabout-reconstruction-v2-20260907` — its own subdirectory
  (`ultimate_pipeline/topology/roundabout_v2/`), touches nothing anyone else touches.

## Group 2 — the geometry-kernel cluster (merge geometry-kernel-v1 FIRST)

4 branches each independently reproduced the exact same kernel work (confirmed byte-identical via
diff, not just "similar"):
- `feature/geometry-kernel-v1-20260907` — the original. **Merge this first.**
- `feature/connector-pose-validation-v1-20260907` — **BLOCKED, do not merge yet.** Fix 1 (the
  map-of-record regression from wiring `gate_junction_connectors=True`) is still unresolved as of
  this writing. Merging as-is would decertify the current map-of-record.
- `feature/osm-correspondence-engine-v1-20260907` — Fix 2 verified landed and correct. Safe to
  merge once geometry-kernel-v1 is in (git will see the kernel file as already-applied/identical).
- `feature/junction-lanelink-geometry-v1-20260907` — **BLOCKED, do not merge yet.** Missing its
  required regression fixture (follow-up prompt already sent).

Once geometry-kernel-v1 lands, `ultimate_pipeline/geometry/geometry_validator.py` and
`opendrive_geometry_kernel.py` will merge as no-ops for the other 3 — confirmed identical diffs,
not just probably-compatible.

## Group 3 — lane-touching cluster, non-overlapping hunks, safe in either order

- `feature/lane-count-from-osm-v1-20260907` — touches `lane_width_policy.py` lines ~152 and
  ~318-338.
- `feature/confirm-then-fix-batch-20260907` — touches `lane_width_policy.py` lines ~213 and
  ~268-278 (different region, same file) plus `traffic_light_infer.py`, `map_hygiene.py`,
  `tiling/tile_extractor.py` (no overlap with anything else).
- `feature/sidewalk-no-fix-20260907` — `sidewalk_builder.py` only, no overlap.

These 3 can merge in any order relative to each other.

## Group 4 — quality-gate cluster, non-overlapping hunks

- `feature/semantic-overlap-wiring-20260907` — touches `quality_gate_manager.py` lines ~113-118
  (the `gate_semantic_overlap` method). Recommend landing its strict-mode follow-up (already
  queued) before merging, not strictly required.
- `feature/quality-gate-fixes-20260907` — `check_junction_integrity.py` + `structure_scanner.py`,
  no overlap with anything else.
- (`connector-pose-validation-v1-20260907`, once Fix 1 lands, will ALSO touch
  `quality_gate_manager.py` at lines ~328-330 — a different method, confirmed no hunk overlap with
  semantic-overlap-wiring's change.)

## The one real conflict: docs/deprecated/

**P3 (contained in P5, per the correction above) and `chore/production-engineering-20260906`
(C0-C16) both independently created `docs/deprecated/README.md` and `docs/deprecated/MANIFEST.yaml`
with genuinely different, incompatible schemas** — P3's is a flat `DEPRECATED_DOCS_MANIFEST_V1`
list with 4 real entries; C0-C16's is an 8-category framework (`CURRENT_AUTHORITY`,
`ACTIVE_RUNTIME`, ... `UNCERTAIN`) with zero entries populated. Confirmed via direct diff, this
will be a real git merge conflict (not auto-resolvable) if both land in the same target.

**Resolution already in motion, not new work**: `OPENCODE_CLEANUP_PROMPTS.md` (committed this
branch, Prompt 1) already tasks OpenCode with populating C0-C16's framework for real, including
the same 4 files P3 scoped. Recommend: **do not merge P5's `docs/deprecated/` changes as a
separate step at all** — let the OpenCode cleanup prompt supersede it entirely (it produces the
same practical outcome — those 4 files archived — under the framework that's already
authoritative on the branch with more total work committed). If P5 is merged for its OTHER
content (the P1/P2/P4 work it contains), the `docs/deprecated/` files specifically should be
dropped from that merge or reconciled by hand, not blindly taken from either side.

## Open question this plan cannot answer: what's the actual target/trunk branch?

None of this addresses WHERE these merge TO. `main` (both local and `origin/main`) is a stale,
unrelated orphan history per this session's own earlier findings — not a real trunk. All real work
this entire session has happened directly on top of the `f195ba0b`/`2e020d9b` lineage across
parallel feature branches, with no designated integration branch identified yet. Before executing
any of the merge order above, that needs an explicit answer: a new `integration/2026-09-XX`
branch created fresh off `f195ba0b`, or one of the existing branches (most likely
`chore/production-engineering-20260906`, since it's already the most-advanced/most-tested and has
zero conflicts with everything else) designated as the de facto trunk that the others merge into.

## Recommended overall order (once the target-branch question is answered)

1. `chore/production-engineering-20260906` (or designate it as target, per above)
2. `feature/geometry-kernel-v1-20260907`
3. `feature/osm-correspondence-engine-v1-20260907`
4. `feature/roundabout-reconstruction-v2-20260907`
5. Group 3 (lane cluster) — any order
6. Group 4 (quality-gate cluster, minus connector-pose-validation) — any order
7. `feature/stale-comment-fixes-20260907` (P5) — **excluding its docs/deprecated/ changes**, per
   the resolution above
8. Once Fix 1 lands: `feature/connector-pose-validation-v1-20260907`
9. Once its regression fixture lands: `feature/junction-lanelink-geometry-v1-20260907`
10. Whatever OpenCode's cleanup pass (`OPENCODE_CLEANUP_PROMPTS.md`) produces, last — it depends
    on the C0-C16 `docs/deprecated/` framework already being in place.

Full offline test suite should be re-run after each merge, not just at the end — a clean merge at
the git level doesn't guarantee behavioral compatibility (e.g. two changes to the same function's
*behavior* via different call sites, which a text-level diff won't flag as a conflict).
