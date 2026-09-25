# Worktree and Integration Hygiene

This repository uses multiple isolated worktrees for L3/L4 engineering tasks. A clean remote branch does **not** prove that local worktrees are clean, nor that uncommitted evidence has been preserved.

## Canonical baseline

Active engineering work starts from:

`integration/production-large-map-20260918`

GitHub's current default `main` is historical until the governance migration is completed.

Before creating a writer worktree:

```bash
git fetch --all --prune
git rev-parse origin/integration/production-large-map-20260918
git worktree list --porcelain
```

Record the canonical remote SHA in the task report.

## Audit every worktree

For every path emitted by `git worktree list --porcelain`, run:

```bash
git -C "<worktree>" status --short --branch
git -C "<worktree>" rev-parse HEAD
git -C "<worktree>" branch --show-current
git -C "<worktree>" diff --stat
git -C "<worktree>" diff --cached --stat
```

Classify each worktree:

- `CLEAN_CURRENT` — clean and based on the intended current lineage.
- `CLEAN_STALE` — clean but behind/superseded.
- `DIRTY_PRESERVE` — contains intentional uncommitted work/evidence that must be committed, exported, or otherwise preserved.
- `DIRTY_UNKNOWN` — unexplained local changes; no merge/cleanup may proceed.
- `CONFLICTED` — merge/rebase conflict; isolate and resolve deliberately.
- `PRUNABLE_VERIFIED` — stale worktree whose branch/evidence is already merged, archived, or explicitly superseded.
- `LOCKED_ACTIVE` — intentionally retained active worktree.

## Cleanup rules

Never use destructive cleanup to make an audit green.

Do not run these until the affected worktree has been classified and preserved:

```bash
git reset --hard
git clean -fd
git clean -fdx
git worktree remove --force
git branch -D
git push --delete
```

Use `git worktree prune --dry-run --verbose` only as a diagnostic first. Remove/prune only entries proven safe.

Untracked reports, logs, candidate maps, manifests, checkpoints, patches, and scientific evidence must be inspected before deletion. If they are required for reproducibility, move them into the governed evidence location or an external immutable artifact store and record hashes.

## Before integration

The implementation worktree must satisfy:

1. no conflicts;
2. no unexplained modified/staged files;
3. no unrelated untracked production artifacts;
4. baseline SHA documented;
5. focused tests complete;
6. complete diff reviewed;
7. frozen `submission/` unchanged.

The coordinator worktree must also be clean before merging.

Integrate one ownership slice at a time. Do not merge multiple overlapping agent branches simply because each reported PASS independently.

## After integration

Run:

```bash
git status --short --branch
git diff --check
pytest
git worktree list --porcelain
```

Then inspect every remaining worktree again. Record:

- branch;
- HEAD;
- relation to production;
- dirty state;
- preservation/retirement decision.

A worktree is not safe to retire merely because its branch is old.

## Evidence preservation

Historical receipts and frozen thesis evidence are immutable. New evidence is additive.

If a worktree contains local-only evidence:

1. determine whether the evidence is authoritative;
2. bind it to Git SHA, input hashes, configuration, and tool versions;
3. commit small textual evidence where appropriate;
4. store large artifacts in the approved durable artifact mechanism;
5. document retrieval location and SHA256;
6. only then retire the worktree.

## Writer ownership

For L4 work, exactly one writer owns a subsystem/worktree. Read-only scouts/reviewers may inspect in parallel.

If two active worktrees touch the same generator, map-registry, promotion, cook, or scientific-contract files, stop and reconcile ownership before further writes.
