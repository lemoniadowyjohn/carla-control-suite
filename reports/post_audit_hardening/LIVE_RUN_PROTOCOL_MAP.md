# Live-Run Protocol Map (read-only trace, 2026-08-13)

How the R17/G19 runtime evidence is produced and consumed, traced WITHOUT editing anything, so a
`6bac3570` re-certification can be executed deliberately (no guesswork, no false-PASS risk).
Server confirmed launchable: `CarlaUE4.exe -carla-rpc-port=2000 -RenderOffScreen -nosound` came up on port 2000.

## The pipeline (4 producers + 1 certifier)

```
[A] _run_p4_equiv.py        loads candidate into CARLA (load_opendrive_world_from_file), to_opendrive(),
                            hashes + road/junction/lane inventory  ->  writes _p4_runtime_evidence.json
        │
[B] _write_p4_evidence.py   formats _p4_runtime_evidence.json  ->  reports/post_audit_hardening/{RUNID}_P4_RUNTIME_EQUIVALENCE/
                            (P04_RAW_RUNTIME_EVIDENCE.json + P13..P18)   [no pin; pure formatter]
        │
[C] phase_l_validation.py   connects to the LOADED map, runs L1..L12  ->  reports/post_audit_hardening/{RUNID}/
                            (L1..L12 + PHASE_L_RUNTIME_VALIDATION.json; includes L11_old_vs_new)
        │
[C2] phase_q/semantic_evidence.py + certifier_decision.py   semantic category counts (G14/G15)  [trace before use]
        │
[D] run_n_certify.py        reads FIXED dirs -> gate matrix -> N18_FINAL_RELEASE_VERDICT.json
```

## The three pins that force the OLD candidate (must change for a 6bac3570 run)

| File:line | Current (OLD) | Change to |
|---|---|---|
| `_run_p4_equiv.py:32` | `REPAIRED = …/ingolstadt_fixed_final.xodr` (`80ebb005`) | `…/ingolstadt_perception_final_repaired.xodr` (`6bac3570`) |
| `phase_l_validation.py:25` | `INGOLSTADT_XODR = …/ingolstadt_fixed_final.xodr` | `…/ingolstadt_perception_final_repaired.xodr` |
| `run_n_certify.py:32-33` | `PHASE_L_EVIDENCE_DIR = BASE/20260805T122525Z`; `P4_EVIDENCE_DIR = BASE/20260805T115947Z_P4_RUNTIME_EQUIVALENCE` | the FRESH `{RUNID}` + `{RUNID}_P4_RUNTIME_EQUIVALENCE` dirs from [A]/[C] |

`_run_p4_equiv.py:31` `SRC = raw_xodr_run_1_epsg32632_header_pinned.xodr` (`ff2a05e7`) = the pre-repair source;
leave as-is (it is the source side of the equivalence diff). `_write_p4_evidence.py` needs **no** edit.

## THE CONSISTENCY INVARIANT (why map-first mattered)

For a *valid* certification every evidence stream must be the **same** candidate:
```
_run_p4_equiv rep_sha256  ==  phase_l L2 identity sha  ==  run_n_certify --candidate-xodr
                          ==  6bac3570ce8f4230836ace27ec26155bbed58171567a6e0afd47e710c86dcb02
```
If any one is missed (e.g. repoint [A] but forget [C]), the certifier consumes **mismatched** evidence.
Depending on which gate reads what, that can manufacture a bogus PASS on inconsistent data — the exact
failure this fail-closed system exists to prevent. Repoint all three or none.

## Execution order (when authorized)
1. Server up on 2000 (done). Pre-gate: `verify_candidate_digest --xodr …_repaired.xodr --expected 6bac3570…` → GO.
2. `[A]` `python _run_p4_equiv.py` — loads `6bac3570` into CARLA; **must print `status: OK`** and
   `rep_sha256=6bac3570…`, `runtime_to_opendrive_sha256=…`, missing/unexpected roads = 0. (This is also the real
   crash-safety test: if the candidate can't load, it fails here — the honest result.)
3. `[B]` `python _write_p4_evidence.py` — formats into a fresh `{RUNID}_P4_RUNTIME_EQUIVALENCE/`.
4. `[C]` `python phase_l_validation.py` — against the SAME loaded session (do NOT reload to a Town first);
   produces a fresh `{RUNID}/` with L1..L12 incl. real FPS (G5), spawns (G6), old-vs-new (G7).
5. `[C2]` semantic counts for G14/G15 (trace `phase_q/semantic_evidence.py` first; supply via `--semantic-counts`).
6. `[D]` repoint `run_n_certify.py:32-33` to the fresh dirs, then
   `python run_n_certify.py --profile perception --candidate-xodr …/ingolstadt_perception_final_repaired.xodr`.
7. Expect G2/G5/G6/G7/G14/G15/G18 → PASS → **20/20**; else stays REJECTED (fail-closed) with the real failing gate.

## Open items to resolve BEFORE executing (still unknown / to confirm)
- **Load path health:** does `load_opendrive_world_from_file` load `6bac3570` crash-free? (the actual test.)
- **Phase-L sequencing:** confirm `phase_l_validation.py` inspects the already-loaded map and does not reload to a
  builtin Town (would void G0/L2). Verify `step_l1/l2` do not `load_world`.
- **Semantic evidence (G14/G15):** trace `phase_q/semantic_evidence.py` — how `--semantic-counts` JSON is produced.
- **G18 manifest re-sign / trailing-refresh:** the ledger's trailing-refresh protocol governs the evidence-commit;
  confirm how the manifest is re-signed after fresh evidence (G18 checks `signature_present`).
- **Governance:** these are edits to certification-pipeline files — they should be a bounded, reviewed change
  (candidate repoint only), NOT a semantics change to any gate.

## Status
Read-only trace complete. No pipeline file edited. CARLA server left running (PID 18244) for the execution phase.
Next decision: authorize the 3-pin repoint + campaign, or resolve the open items first.
