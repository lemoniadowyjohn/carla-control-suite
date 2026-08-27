# C19 assembly orchestrator added — prevents the evidence-bundle staleness bug from recurring

## Root cause this closes
The 4 C19 steps (`export_thesis_tables.py`, `audit_thesis_topic_contract.py`,
`validate_thesis_claim_provenance.py`, `pack_thesis_run.py`) had no orchestrator — each was
only ever run by hand, individually. That is exactly how the committed evidence bundle went
stale after the C29 pin promotion earlier this session: the registry and `rq_tables.json`
were updated, but the other 3 steps were never re-run, so `contract_audit.json` /
`provenance_validation.json` / `thesis_run_bundle.json` silently kept citing pre-promotion
state until caught by chance (see
`FRECHET_ROW_WIRED_AND_PROVENANCE_VALIDATOR_REGRESSION_FIXED.md`).

## What was built
`tools/run_c19_assembly.py`: runs all 4 steps together, in the required dependency order
(export first — the other 3 all read its output; provenance validation — the honesty gate —
before pack, so the bundle reflects a freshly-verified state, not a stale one). **Fail-closed**:
stops at the first step that exits nonzero rather than building later steps on top of a
known-bad intermediate state.

Also fixes a real usage footgun the two inconsistent `--out` conventions create: two of the
four scripts take `--out <directory>` and write fixed-named files inside it, the other two
take `--out <file>` and write directly to that exact path. Mixing these up by hand (as
happened once already this session, passing a would-be filename to the directory-style
script) silently creates a directory named like a JSON file instead of writing the JSON. The
orchestrator hardcodes the correct form for each step so this can't happen again.

## Verification
- TDD: `tests/unit/test_run_c19_assembly.py`, 4 tests — step ordering, correct `--out` form
  per step (regression-guards the footgun above), and `run_steps`' fail-closed behavior
  (stops at the first failing step, later steps never invoked) using a fake runner, no real
  subprocess calls needed for the unit-level logic.
- Real end-to-end run (`python tools/run_c19_assembly.py --out-dir
  reports/post_audit_hardening/C19_THESIS_ASSEMBLY`): exit 0, all 4 real steps ran, output
  identical (modulo a `generated_at_utc` timestamp) to the already-verified-correct bundle
  committed in the previous two commits — confirms the orchestrator is a faithful,
  idempotent wrapper around the existing steps, not a reimplementation.
- Full unit suite: see commit for exact pass count, 0 regressions expected.

## Recommendation, not enforced here
Future changes that affect any C19 evidence (pin promotions, new RQ rows, registry edits)
should regenerate via `python tools/run_c19_assembly.py`, not by running individual steps by
hand. Not wired into a pre-commit hook or CI gate in this pass — that would be a further,
separate governance decision.
