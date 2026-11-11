# Evidence admission matrix

| State | Meaning | Required evidence | Who can grant it | Reachable today? |
|---|---|---|---|---|
| `NOT_MEASURED` | no capture or metric exists | — | — | current state for RQ3, RQ5a, RQ5b |
| `PILOT_VALIDATED` | the procedure works; **no RQ number** | pilot checks §3.1-3.9 all pass; manifests hashed | operator + independent reviewer | no (G0 blocked) |
| `MEASURED_NOT_ADMITTED` | a capture and metrics exist and are hash-bound | full capture per contract; contract audit PASS; `COMPLETED` terminal; digests resolve to real bytes; metrics computed per the frozen protocol and analysis plan | the pipeline + an independent reviewer of the analysis | no |
| `SIGNED_ADMITTED` (`DATASET_ADMITTED`) | admitted as thesis evidence | everything above + an Ed25519 receipt from a key in `review_trust_root`, bound to the dataset and capture digests and the session, unexpired, unrevoked, reviewer ≠ capture operator (`rq3_evidence_gate.py`) | an external reviewer with a trust-root key | **no: no trust root exists** |
| `EXTERNAL_DATA` | needs data the project does not have | a labelled real-world Ingolstadt dataset | data provider | RQ5b |

**Rules:**
- No state may be skipped.
- A pilot never produces an RQ3 number.
- An unpaired capture (§3.7 fails) is never called paired RQ3.
- Any missing input means NOT_RUN / UNVERIFIED, never PASS.
