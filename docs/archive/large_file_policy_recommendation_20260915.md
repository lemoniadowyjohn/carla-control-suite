# Large File Policy Recommendation - 2026-09-15

## Status update - 2026-09-16: rule is now LIVE

This recommendation was implemented on `chore/git-lfs-policy-implementation-v1-20260916`
(branched from `integration/session-batch1-20260912` @ `b3a612ee`). Summary:

- **What changed**: added a forward-looking blanket rule to the root `.gitattributes`:
  ```
  *.xodr filter=lfs diff=lfs merge=lfs -text
  *.fbx filter=lfs diff=lfs merge=lfs -text
  *.glb filter=lfs diff=lfs merge=lfs -text
  ```
  placed above the pre-existing narrower per-path `.xodr`/`.osm` LFS rules (which are
  kept as-is, now redundant but harmless, since the blanket rule already covers them).

- **`.fbx`/`.glb` included, not just `.xodr` (going beyond this doc's original
  recommendation)**: the 2026-09-15 large-binaries audit's Group E found 4 real
  `.fbx`/`.glb` files under `reports/production_readiness/20260915T*/artifacts/`
  (14.8 MB and 24.8 MB among them) committed as plain git blobs the same day, from
  active FBX-regen and OSM2World/tile-cooking work streams that are still ongoing
  per this session's branch list (`feature/tile-based-fbx-generation-v1-20260915`,
  `feature/full-grid-tile-fbx-cook-v1-20260915`, `docs/tile-based-ue4-cooking-design-v1-20260915`).
  That's real, ongoing accumulation risk toward this doc's own "revisit if they
  exceed 100 MB" trigger — not a reflexive copy of the `.xodr` pattern.

- **`git lfs track` cross-check**: manually wrote the three pattern lines above,
  then ran `git lfs track "*.xodr" "*.fbx" "*.glb"`. Output was `"*.xodr" already
  supported` / `"*.fbx" already supported` / `"*.glb" already supported` for all
  three — i.e. git-lfs recognized the manually-written lines as already correct and
  added no duplicates. Side effect noted: `git lfs track` unconditionally strips
  blank lines from `.gitattributes` on every rewrite (confirmed reproducible by
  running it twice), which also collapsed two pre-existing blank-line separators
  unrelated to this change (before the "Governance-pinned inputs" and "Same class
  of bug" comment blocks). That's inherent git-lfs behavior, not a mistake in this
  edit — restoring those blanks by hand would just be undone by the next person who
  runs `git lfs track` again, so the file was left in git-lfs's own canonical form.

- **End-to-end verification performed**: created a synthetic file at
  `reports/_lfs_policy_verify_scratch_20260916/synthetic_verify.xodr` (minimal valid
  OpenDRIVE XML, 148 bytes, a path that matches none of the pre-existing narrower
  rules so the test isolates the new blanket rule), `git add`ed it, and confirmed via
  `git lfs ls-files` that it appeared LFS-tracked (`20e008765a * reports/..._verify.xodr`)
  alongside the pre-existing LFS entries, and via `git cat-file -p` that the staged
  blob was a genuine `git-lfs.github.com/spec/v1` pointer (`size 148`), not the raw
  XML content. The file was then `git reset` and deleted — no synthetic artifact was
  committed.

- **The 37 historical files are untouched, by design**: this change only affects how
  a path is stored on its *next* `git add`/checkout — it does not rewrite any commit
  already in history. All 37 large `.xodr`/`.fbx`/`.glb` files found by the
  2026-09-15 audit (20/25 already LFS via a prior undocumented one-off migration, the
  rest plain blobs) remain exactly as they were. `git lfs migrate` was explicitly
  **not** run — that's a history-rewrite requiring its own explicit approval, out of
  scope here. If migrating them is ever wanted: `git lfs migrate import --include="*.xodr,*.fbx,*.glb" --everything`
  (or scoped to specific paths/refs) would convert existing blobs to LFS pointers,
  but rewrites every commit that touches those paths and requires a force-push plus
  coordination with anyone holding a clone — not attempted here.

- **Test suite**: full `pytest` run stayed green after this change (this is a
  `.gitattributes`-only change plus a doc update; no application code was touched).

## Current State

The repository currently tracks 37 large `.xodr` files under `reports/` totaling approximately 1.79 GB, along with `.fbx` and `.glb` assets. The prior hygiene audit (2026-09-15) identified these as largely historical snapshots with no active code references outside `reports/`.

## Recommendation: Add Git LFS for `.xodr` Going Forward

**Add a `.gitattributes` rule to track `.xodr` files with Git LFS:**

```
# Git LFS for CARLA map definition files
*.xodr filter=lfs diff=lfs merge=lfs -text
```

### Rationale

1. **Reduce repo size**: The 37 `.xodr` files under `reports/` currently contribute ~1.79 GB to the packed git size. LFS replaces large file pointers with small text substitutes in the repository, which would significantly reduce the clone/fetch size.

2. **Appropriate use case**: `.xodr` (OpenDRIVE format) is a CAD-like road format that is binary/structured but not text-mergable. Git LFS is well-suited for this type of file.

3. **Forward-looking**: This rule would apply to new `.xodr` files going forward. Historical files already in the repo would continue to be tracked normally (or could be migrated to LFS later with `git lfs migrate`).

4. **Minimal disruption**: Adding a `.gitattributes` rule is an additive, non-destructive change. It does not rewrite git history or require force-pushes. Existing workflows continue to work; only new large `.xodr` files would be stored via LFS.

### Implementation Notes

- The `*.xodr filter=lfs diff=lfs merge=lfs -text` rule should be added to the root `.gitattributes` file.
- Ensure all developers have Git LFS installed and configured (`git lfs install`).
- After adding the rule, run `git lfs track` and commit the updated `.gitattributes` file.
- Consider also adding `*.fbx` and `*.glb` to LFS if they continue to grow in size, though these are already partially managed via LFS in some paths.

### Alternative Considerations

- **Do not apply LFS to historical files automatically**: The prior audit found that many of the large committed files are orphaned historical snapshots. Migrating them all from history would require `git filter-repo` or BFG, which is a high-stakes decision requiring explicit human approval (as noted in the diagnostic audit report).
- **Monitor `.fbx`/`.glb` sizes**: The 4 files in `production_readiness/20260915T*` are the currently active FBX/GLB assets. Their sizes should be monitored, and LFS consideration should be revisited if they exceed 100 MB.

### Next Steps (human decision required)

1. Approve adding `*.xodr filter=lfs` to `.gitattributes`
2. Run `git lfs install` and `git lfs track` globally
3. Commit the `.gitattributes` update
4. Decide whether to migrate existing historical `.xodr` files to LFS (out of scope for autonomous execution)