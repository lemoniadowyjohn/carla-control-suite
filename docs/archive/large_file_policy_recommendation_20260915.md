# Large File Policy Recommendation - 2026-09-15

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