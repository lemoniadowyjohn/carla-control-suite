# Release-safety review checklist (to use after the other agents finish)

Baseline: `integration/post-pr16-final-20261102@1a36b560`. Every item states what this review saw and
what a reviewer must check. "Not located" means the item was in the brief but this review did not
independently find its code. Treat it as **unverified**, not as fine.

## A. Terminal SUCCESS publication ordering (P0-TC-001)
- **Seen:** work in progress in `E:/wt/p0-tc-001-terminal-release-authority-20261104`, based on
  `1a36b560`. It is **uncommitted**: 3 modified files, `ultimate_pipeline/main_pipeline.py`,
  `ultimate_pipeline/utils/finalize_run_pack.py` and `tests/adversarial/test_terminal_authority.py`.
  Its own report: 21 focused tests pass, plus 52 passed and 1 skipped; the reviewer asked for more.
- **Check:**
  - [ ] Order: PASS verdict → atomic terminal status → signed pack → verify → atomic SUCCESS →
    reverify. Prove it with a test that injects a failure between every pair of steps, and assert that
    no `SUCCESS.txt` exists after any injected failure.
  - [ ] FAIL and INCOMPLETE verdicts end with no SUCCESS and with terminal status = that verdict.
  - [ ] A terminal-status write failure fails closed (exception, no SUCCESS).
  - [ ] A post-publication verification failure revokes SUCCESS (`core/terminal_authority.py:21-42`
    revocation path).
  - [ ] Restart: a stale SUCCESS from a prior run is revoked before any mutation (`main_pipeline.py:981`).
  - [ ] A concurrent reader never sees SUCCESS without a matching verified pack (os.replace atomicity;
    Windows rename semantics).
  - [ ] Committed, single writer, reviewed by a different model family.

## B. GAP-052 read-only worktree lease bypass (not located)
- **Pointers:** `ultimate_pipeline/governance/single_writer/preflight.py:7` ("Read-only session:
  MUTATION_DENIED_READ_ONLY_SESSION"), `worktree_lock.py`, `common_git_lock.py`;
  `tests/unit/test_single_writer_arbitration.py:44-50`.
- **Check:**
  - [ ] Find the bypass path from the GAP-052 register entry.
  - [ ] A failing-first test showing that a read-only session cannot mutate through it.
  - [ ] A fix that keeps the O_CREAT|O_EXCL exclusion.

## C. RQ5 failure-path correctness
- **Seen:** the launcher fixes are merged (`is_main` assigned before use, a single DDP init, rank-safe
  stale-SUCCESS revocation, DDP cleanup on every exit path, `weights_backbone=None`, `--contract` with
  no silent fallback). The brief lists failure-path correctness as unresolved; the specific defect was
  not located.
- **Check:**
  - [ ] For every early-exit path in the training launcher (disk guard, contract load, data load,
    OOM, KeyboardInterrupt): no SUCCESS, the DDP group is destroyed, and the receipt records the
    failure.
  - [ ] One test per path, failing first.

## D. Crop geometry-sampling fallback
- **Seen:** `ultimate_pipeline/domain_gap/footprint_crop.py:217-223`. When kernel sampling raises, the
  road is tested with **only its anchor point**. A road that crosses the footprint but has its anchor
  outside is **dropped**, which contradicts the comment ("never silently drop coverage"). The count is
  reported (`sampling_fallback_count`, manifest; **0** on the real crop), but it is **not** one of the
  7 hard checks.
- **Also:** the pre-filter at `:213-216` assumes `@length` ≥ the displacement from the anchor (an
  arc-length bound). The GAP-070 candidate breaks that assumption: arc lengths are up to 3.7× `length`
  (review F-03). Rule (b) currently applies to non-junction roads, which the candidate does not
  modify, so it is safe today. It becomes unsafe if either side changes.
- **Check:**
  - [ ] Make `sampling_fallback_count == 0` a hard check (fail closed), with a failing-first test
    using a malformed geometry.
  - [ ] Document the arc-length assumption in the pre-filter, and add an assertion that it holds.

## E. Candidate-bound evidence
- **Seen:** the GAP-070 measurement receipt (`03aaccd4`) and this review's numbers both come from a
  local, untracked stage-5 file (sha256 `45c52059…`). The X9 inventory branch is local only.
- **Check:**
  - [ ] Every receipt records its input sha256 and the input's location.
  - [ ] Inputs are archived somewhere a GitHub reviewer can reach (backlog C0).
  - [ ] Receipts are bound to the code SHA that produced them.
  - [ ] No receipt is cited as acceptance evidence for a SHA other than the one it measured.

## F. Signed RQ3 review admission
- **Seen:** admission requires an Ed25519-signed review receipt from a key in `review_trust_root`. No
  trust root exists, so admission is impossible **by design**.
- **Check:**
  - [ ] No document claims RQ3 admitted or measured.
  - [ ] The trust-root bootstrap is an operator procedure, documented and not automated.

## G. Live CARLA runtime
- **Seen:** GAP-077. 4 headless attempts timed out at `wait_for_carla_ready`; no TDR. Port
  listening ≠ success (AGENTS.md).
- **Check:**
  - [ ] No claim of CARLA load or traversal for the crop or for any X8 candidate without an RPC
    response and a receipt.
  - [ ] Offline CI green is not runtime certification.

## H. Windows CI coverage
- **Seen:** every job in `.github/workflows/tests.yml` uses `runs-on: ubuntu-latest` (lines 40, 124,
  194, 220, 249, 283, 309). `carla-runtime.yml:40` is self-hosted. The single-writer arbitration tests
  are **Windows-only** (`test_single_writer_arbitration.py:49`, skipif not win), so they **never run in
  CI**, while development and execution happen on Windows (path, CRLF, rename and locking semantics).
- **Check:**
  - [ ] Add a `windows-latest` job that runs at least the single-writer, terminal-authority, atomic-I/O
    and path-handling tests.
  - [ ] Confirm the job actually runs them (they are collected, not skipped).

## I. Geometry (from this review)
- [ ] GAP-070 candidate: F-01 to F-05 fixed and re-measured (`CLAUDE_GEOMETRY_ARCHITECTURE_REVIEW.md`).
- [ ] X8 run with all three arms, the full invariant matrix and the independent recomputation.
- [ ] GAP-070 entry updated: the "~53° kinks" are the 3,375 U-turn connectors (new addendum; the
  existing ones are immutable).
