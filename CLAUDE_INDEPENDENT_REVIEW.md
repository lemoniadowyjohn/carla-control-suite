# CLAUDE Independent Technical & Research-Integrity Review

**Role:** Independent reviewer / research-integrity auditor. The implementation agent was Codex; none of its conclusions were taken on trust. Every finding below was re-derived from the live repository.

- **Repository:** `lemoniadowyjohn/carla-control-suite`
- **Branch under review:** `stabilize/research-release-20260905`
- **HEAD:** `33d5d815b1d7cec9052157cb03ef2f7c9a7204dc`
- **Worktree:** clean
- **Stabilization delta reviewed:** `ebeff542..HEAD` = 14 commits, 63 files, +3575/-492
- **Date:** 2026-09-06
- **Thesis source of truth:** `submission/thesis_source/Chapter1/chap1.tex:24-28` (read directly; the immutable RQ labels match verbatim)

---

## Bottom line

**CONDITIONAL GO.**

The stabilization work is genuine, careful, and root-cause-oriented. Every adversarial check (A–J) passed on the merits, several of them impressively so (RQ semantics, R13 frozen-evidence integrity, repo-health fail-closed logic). The research claims are correctly bounded: no post-thesis novelty is asserted for results the thesis already established, RQ2 map-improvement is explicitly marked *incomparable/not-run*, and RQ3/RQ5 remain deferred.

The single blocking condition is **process, not code**: the release-defining CI has never actually run on this HEAD. The branch is unpushed; the last green GitHub CI run validated `b059a9d0` (commit 6 of 14) using the *old* single-job workflow, and the new six-job "offline research gates" workflow — the gates that certify the release — was added *after* that run and has zero runtime evidence.

---

## What each check found

| Check | Area | Verdict | Key evidence |
|---|---|---|---|
| A | Global print/import state | **PASS** | Independent both-order import probes keep `builtins.print` identity; JSON stays parseable; module-scope `enable_timestamped_print()` removed from `cli.py`/`run_pipeline.py`; remaining calls inside `__main__`/`main()`. Root-cause fix, not a timestamp-strip. |
| B | Semantic recorder round-trip | **PASS** (offline) | Per-sensor callback routing; 20-trial cross-write race regression; `semseg_raw` is mode-`L` raw ids; `SegDataset` round-trip; `[0..28]∪{255}` enforced in `carla_classes.py:26`, 255 = CARLA `Any` sentinel, not relaxed. Uses faithful CARLA fakes (live path is out of offline scope). |
| C | Determinism on clean clone | **PASS** (note) | Portable `report.json` check (3 distinct sha256, identical structural signature); raw `run_*.xodr` gitignored + clean skip; narrow `_normalize_timestamps`; positive + negative controls both present. Note: `report.json` lacks tool/version binding (acceptable — claim is `BOUNDED`). |
| D | R13 frozen evidence | **PASS** | **Blob-OID identity** at freeze commit `5f98a666` vs HEAD proves content unchanged since freeze; line-ending explanation *proven* (manifest CRLF hash == frozen tag `manifest_sha256`; override == real LF blob hash); additive tolerant comparator + one documented override, no frozen file mutated; 18/18 tests incl. tamper negatives. |
| E | Wheel packaging | **PASS** (completeness) | Wheel contains `ultimate_pipeline` (791), `opendrive_geometry` (10), `phase_q` (21), `sensors`/`tools` (namespace); installs to a clean venv (`--no-deps`), nested subpackages import from the wheel (editable avoided). Residual: the untested `package-wheel-smoke` CI gate; `up --help`/`pip check` under declared-deps-only unverifiable offline. |
| F | Thesis RQ semantics | **PASS** | Labels match `chap1.tex` verbatim; `metric_allowed_for_rq` fails closed and is wired into the audit (0 violations live); all "reject" mappings correctly placed; **regenerated `rq_tables.json` is byte-identical to committed** → evidence is producer-emitted, not hand-edited. |
| G+H | Novelty + statistics | **PASS** | Novelty correctly classified (see `CLAUDE_RESEARCH_CLAIM_AUDIT.json`); RQ2 map-improvement `NOT_RUN`/incomparable; RQ4 bounded as a multi-seed *extension* (thesis p<0.001 preserved). Caveats: RQ4 n=5 bootstrap is fragile; C21 stats omit tile split. |
| I | Repo health + CLI authority | **PASS** | `_overall_status` fail-closed: runtime `NOT_RUN` → `INCOMPLETE` (never a false `PASS`); live run = `INCOMPLETE` with 6 evidence sections `PASS`; canonical `up` group coherent (`up health`, `up research status`). Notes: `authoritative_lineage` hardcoded to parent branch; CLI version `2.0.0` ≠ pyproject `0.1.0`. |
| J | Documentation (README) | **PASS** | Covers purpose, CARLA 0.9.16, branches, canonical `up`, map-of-record (file exists + matches pin `2ca342d8`), reproducibility, RQ1–5 status (matches `up research status`), evidence location. Minor: manual Grid0828 reference not explicitly named; CI section doesn't disclose the branch is unpushed. |

---

## CI status — the one that matters

- `stabilize/research-release-20260905` has **no upstream and 0 CI runs**.
- Most recent **success**: run `34025666555` on `b059a9d0` (branch `fix/post-audit-phase-e-…`), **old single-`pytest` workflow**.
- `b059a9d0` is commit **6 of 14**; the 8 later commits — including `2ad41e76` which *adds the six-job workflow* — have never been through GitHub CI.
- Consequence: `package-wheel-smoke`, `governance-integrity`, `thesis-rq-contract`, `research-provenance`, and the gated `repository-health` jobs have **zero runtime evidence**.
- Local offline suite at HEAD (this machine, Windows/Py3.12): **5743 passed, 79 skipped, 0 failed** — but local-green ≠ Linux-CI-green (repo history is full of CRLF/GEOS bugs that only surfaced on Linux).

This is why the verdict is **CONDITIONAL**, not GO.

---

## Live CARLA runtime

**LIVE CARLA RUNTIME: UNVERIFIED.** No runtime evidence was inspected and none exists on this machine; the pipeline's own reports characterize a persistent CARLA RPC-hang (isolated via `-nullrhi`, independent of the GPU driver). Correctness of any live-CARLA path is **not** inferred from the passing unit tests. RQ3 and RQ5 remain bounded/deferred precisely because of this.

---

## Minor issues found (non-blocking; recommend fixing, not blocking release)

1. `ultimate_pipeline/tools/repo_health.py` — `authoritative_lineage` hardcoded to `fix/post-audit-phase-e-…`, stale vs the actual `stabilize/research-release-20260905`. (README carries the same dual labeling but is at least explicit about both.)
2. `ultimate_pipeline/cli.py` — `@click.version_option(version="2.0.0")` disagrees with `pyproject.toml` `version = "0.1.0"`.
3. `reports/.../C15_RQ4_DR/determinism/report.json` — no tool/version binding for the "timestamps are the only byte-level source" claim (claim is `BOUNDED`, so acceptable, but a version stamp would close it).
4. `reports/.../C21_GNN_AUTHORITATIVE/aggregate_stats.json` — omits tile counts and train/eval split; record them to fully exclude tile-overlap pseudo-replication for the RQ4 diagnostic.
5. RQ4 bootstrap CI rests on n=5 seeds — state the small-sample limitation next to the CI.
6. `README.md` — name the manual reference (Grid0828) explicitly and disclose the true CI state (last green SHA + branch-unpushed) for a research-integrity reviewer.
7. `audit_thesis_topic_contract._find_run11_source` — Windows dev-machine sibling-path fallback; harmless but non-portable.

None of these are falsifications, integrity failures, or test weakenings. They are documentation/robustness polish.

---

## Highest-priority unresolved action

**Push `stabilize/research-release-20260905` to origin and confirm the full six-job `offline research gates` workflow passes on HEAD `33d5d815` on Linux CI.** The gates that define this release (packaging, governance, RQ contract, provenance, repository-health) have never executed; until they do, "CI green" for this HEAD is unproven.
