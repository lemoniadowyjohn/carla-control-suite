# W-D integration/acceptance owner — original 26-test selection recovery and authorization

**Authority:** This prompt is a research/decision request, NOT a grant of integration authority. Only a **real W-D acceptance owner** can approve substitute test selection. Independent agents may research, but may not impersonate the owner or approve their own reconstruction.

## First priority: recover original selection from primary evidence
1. Freeze local worktree/branch/commit identities and evidence roots. Read-only search candidate/reference branches, tracked acceptance scripts, CI YAML, pinned pytest node-ID lists, original log headers, test collection output, historic ZIP archives, previous operator receipts and verified GitHub commit history. Do not overwrite the historical materials.
2. Recover exact **26 pytest node IDs**, their original order (or sorted canonical policy), selection markers/expressions, fixtures, map identities, dependencies, expected platform, environment, exit semantics, original source SHA, contract version and the approving owner/signoff. A count of 26 alone does not establish test identity.
3. Show byte-level support for each recovered node ID: primary artifact path/hash and source lines/log excerpt. Resolve renamed/moved tests with explicit mapping to original assertions and frozen acceptance thresholds, not silently swapped modern tests.
4. Validate test identities against the **actual candidate** with `pytest --collect-only` only when disk and environment permit; collected count must not be mistaken for executed results. If any original test is unavailable, record it and classify selection INCOMPLETE; never shrink acceptance scope silently.

## When original selection genuinely cannot be recovered
Prepare `WD_RECONSTRUCTED_ACCEPTANCE_CANDIDATE.md` separately. Clearly label the alternate 26-nodeid (or differing count) list as **replacement / NOT original equivalent**; show why original evidence is unrecoverable, coverage map of original requirements, negative controls, loss-of-coverage risk, and exact user-visible change in acceptance semantics. Request an explicit written decision from the authentic integration/acceptance owner that identifies:
- owner principal/authority and source of that authority;
- exact candidate SHA(s) and intended run/platform;
- named alternate list + immutable SHA-256 manifest;
- what it replaces, tolerances unchanged and any added risks;
- approval scope, timestamp and expiry/revocation semantics.

Until that actual authorization exists: `WD_ACCEPTANCE=BLOCKED_OWNER_AUTH`. A synthetic list of 26 cannot be relabeled the original.

## Outputs
`WD_SEARCH_PROVENANCE.json`, `WD_ORIGINAL_26_NODEIDS.txt` **only if genuinely recovered**, `WD_ORIGINAL_ACCEPTANCE_RECEIPTS.md`, optional `WD_RECONSTRUCTED_ACCEPTANCE_CANDIDATE.md`, `WD_OWNER_AUTHORIZATION_REQUEST.md`, `WD_AUTHORITY_VERDICT.json`, `SHA256SUMS.txt`. No production edits, merges, tests executed on low disk, fabricated identities or self-approval.
