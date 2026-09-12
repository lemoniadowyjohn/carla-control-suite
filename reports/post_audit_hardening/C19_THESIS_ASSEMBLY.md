# C19 — Thesis assembly + honesty gate (RQ-delivery report)

Assembles every RQ result from C12-C18 into one provenance-backed, honestly-bounded report. Built 4
tools (3 new, 1 existing reconciled) rather than transcribing numbers by hand, so re-running the same
4 commands reproduces this report from the evidence on disk.

## Steps executed

1. **`tools/export_thesis_tables.py`** → `C19_THESIS_ASSEMBLY/rq_tables.{json,md}` — 22 rows across
   RQ1-RQ5, each with an explicit status, claim boundary, comparability field, and where applicable
   a cited artifact sha256.
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
| **RQ1** (determinism) | AUTHORITATIVE for raw byte non-repeatability and structural repeatability; BOUNDED for timestamp-normalized byte evidence | Three repeated Osm2Odr outputs differ at raw hash level while road/junction/length signatures match. Portable committed fixtures prove timestamp-only differences normalize to one hash and structural changes still fail. |
| **RQ2** (structural domain gap) | BOUNDED | Local manual-footprint comparison quantifies lane-width, curvature, completeness-ratio, building-density, and Fréchet gaps against Grid0828. The legacy C14 directory name contains `RQ1`, but its semantic authority is thesis RQ2. |
| **RQ3** (perceptual domain gap) | DEFERRED_RUNTIME | No generated-vs-manual paired Ingolstadt capture executed. Town10HD remains sensor-rig smoke/control evidence only and does not answer RQ3. |
| **RQ4** (structural variability and latent representation) | AUTHORITATIVE extension | Thesis baseline already fixed NT-Xent collapse and found latent separation with K=1000 permutation p<0.001. Current C21 evidence strengthens that with a 5-seed union-domain ensemble and bootstrap CI; explicit DR wiring is implementation evidence, not a completed natural-vs-explicit DR experiment. |
| **RQ5** (generalization and transfer) | DEFERRED_RUNTIME / DEFERRED_EXTERNAL_DATA | RQ5(a) needs valid RQ3 datasets and a frozen generated-trained checkpoint evaluated on generated/manual holdouts. RQ5(b) needs an operator-supplied real-world dataset; unlabeled shift alone is not generalization accuracy. |

Counts: 5 AUTHORITATIVE, 13 BOUNDED, 3 DEFERRED_RUNTIME, 1 DEFERRED_EXTERNAL_DATA, 0 NOT_RUN
(every metric this tool knows about has real evidence or an explicit deferral reason — nothing was
silently skipped).

## What would move the needle next (not attempted here — out of C19's offline scope)
- RQ3 paired capture: needs either C20's CARLA livelock resolved or the C16 UE cook completed.
- RQ4 robustness extension: execute governed natural-vs-explicit variability comparisons rather than only
  documenting domain-randomization code.
- RQ5(a): needs valid RQ3 datasets before transfer training/evaluation.
- RQ5(b): needs an operator-supplied real-world Ingolstadt dataset.

## Verdict

`THESIS_ASSEMBLED rq1=AUTHORITATIVE_STRUCTURAL_BOUNDED_BYTE_SOURCE rq2=BOUNDED rq3=DEFERRED_RUNTIME rq4=AUTHORITATIVE_EXTENSION rq5=DEFERRED_RUNTIME_AND_EXTERNAL_DATA all_claims_provenanced=YES`
