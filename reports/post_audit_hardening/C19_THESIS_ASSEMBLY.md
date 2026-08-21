# C19 — Thesis assembly + honesty gate (RQ-delivery report)

Assembles every RQ result from C12-C18 into one provenance-backed, honestly-bounded report. Built 4
tools (3 new, 1 existing reconciled) rather than transcribing numbers by hand, so re-running the same
4 commands reproduces this report from the evidence on disk.

## Steps executed

1. **`tools/export_thesis_tables.py`** → `C19_THESIS_ASSEMBLY/rq_tables.{json,md}` — 14 rows across
   RQ1-RQ5, each with an explicit status and, where applicable, a cited artifact sha256.
2. **`ultimate_pipeline/tools/audit_thesis_topic_contract.py`** (new `current_rq_tables_audit`
   section, additive to the pre-existing legacy run11-era checks) → `contract_audit.json` —
   `current_rq_tables_audit.ok = true`, zero violations.
3. **`tools/validate_thesis_claim_provenance.py`** → `provenance_validation.json` — `ok = true`: both
   pinned maps verify against `carla_tools.map_registry`, all pinned generation inputs verify against
   `INPUTS_MANIFEST.json`, every RQ-table claim's cited artifact independently re-hashed and matches.
4. **`tools/pack_thesis_run.py`** → `thesis_run_bundle.{json,md}` — maps by sha, protocol snapshot,
   every per-RQ evidence report (present/missing checked, not assumed), claim boundaries.

## RQ summary

| RQ | status | headline |
|---|---|---|
| **RQ1** (structural gap) | BOUNDED (6/6 aspects) | Auto/manual agree where directly comparable (lane width 0.042); larger gaps are construction/scope artifacts, not domain gap; curvature gap corrected 1.0→0.093 (was a measurement bug). |
| **RQ2** (perceptual gap) | DEFERRED | No paired capture executed — blocked on either a working live CARLA server (currently a confirmed livelock, see C20) or the C16 UE cook (blocked on a human operator). Zero evidence exists yet; not a partial result. |
| **RQ3** (generalization, mIoU) | DEFERRED (2 of 3 components) / PROTOTYPE (1) | mIoU train/eval and domain adaptation (CORAL/MMD) both need C17 captures — blocked, same as RQ2. The GNN latent-gap component (cosine_distance 1.14) is a real, reproducible number but explicitly PROTOTYPE — one-sided training makes the manual map out-of-distribution, so it corroborates RQ1 rather than standing as an independent authoritative result. |
| **RQ4** (domain randomization) | AUTHORITATIVE (3/3) | Natural DR is absent (Osm2Odr is structurally deterministic across 3 runs); explicit DR (`RealismAugmentor`) is wired and verified (5 distinct variants, seeded, deterministic). |
| **RQ5** (real-world shift) | DEFERRED | No real-world Ingolstadt dataset exists on this machine — independent of the CARLA blocker, a separate, still-open gap. |

Counts: 3 AUTHORITATIVE, 6 BOUNDED, 1 PROTOTYPE, 4 DEFERRED, 0 MISSING (every metric this tool knows
about has real evidence or an explicit deferral reason — nothing was silently skipped).

## What would move the needle next (not attempted here — out of C19's offline scope)
- RQ2/RQ3(mIoU+adaptation): needs either C20's CARLA livelock resolved or the C16 UE cook completed.
- RQ3 GNN → AUTHORITATIVE: train on the union of both maps' tiles (Grid0828 isn't tiled yet) +
  seed-ensemble CI, per C18's own stated follow-up.
- RQ5: needs an operator-supplied real-world Ingolstadt dataset.

## Verdict

`THESIS_ASSEMBLED rq1=BOUNDED rq2=DEFERRED rq3=PARTIAL(prototype+deferred) rq4=AUTHORITATIVE rq5=DEFERRED all_claims_provenanced=YES`
