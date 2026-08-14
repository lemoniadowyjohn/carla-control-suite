# Live-Run Runbook — R17/G19 Certification of `6bac3570`

Operator runbook for the one remaining blocker: a live CARLA run that re-collects P04/runtime evidence on the
**signed** candidate so the 7 stale-anchor gates flip and `run_n_certify` reaches 20/20.
Cross-ref: `SUMMARY_R17_G19.md`, `CANDIDATE_DIGEST_INVENTORY.md`, `MIRROR_DRIFT_ADJUDICATION.md`.

Requires a live CARLA server (0.9.16, server/build pin `10033a16`) — this runbook is the *only* step that runs CARLA.

## Fixed identities
- **SIGNED candidate:** `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final_repaired.xodr`
  sha256 `6bac3570ce8f4230836ace27ec26155bbed58171567a6e0afd47e710c86dcb02` (UNTRACKED ~80 MB — verify before use).
- **Do NOT use:** `ingolstadt_fixed_final.xodr` (`80ebb005`, superseded/broken) or `_repaired_v2.xodr` (`1f2b5ff0`).

## Step 0 — server up
Launch CARLA and confirm the RPC port is reachable:
```
& "E:\CARLA\CARLA_0.9.16\CarlaUE4.exe" -carla-rpc-port=2000
```
(Watch for the known streaming-port failure mode — see the Grid0828 runbook.)

## Step 1 — GATE: candidate identity (MUST be GO before proceeding)
```
python tools/verify_candidate_digest.py `
  --xodr campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final_repaired.xodr `
  --expected 6bac3570ce8f4230836ace27ec26155bbed58171567a6e0afd47e710c86dcb02
```
Expected: `GO  6bac3570…` and exit code 0. **If NO-GO, STOP** — the local file is wrong/absent; re-fetch the signed
candidate (verify against the digest above) before spending a runtime pass. This gate is what prevents the
`80ebb00`-vs-`6bac3570` wasted-run trap.

## Step 2 — re-collect P04 / Phase-L evidence on 6bac3570
Run the Phase-L/P04 runtime collection against the signed candidate on the pinned server, then re-certify:
```
python run_n_certify.py --profile perception `
  --candidate-xodr campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final_repaired.xodr
```

## Step 3 — expected result
The 7 stale-anchor gates flip to PASS on fresh evidence:
`G2` (candidate hash now `6bac3570`), `G5` (real FPS), `G6` (real spawns), `G7` (old-vs-new evidence),
`G14`/`G15` (semantic counts), `G18` (manifest re-signed) → **20/20**, `PHASE_N_CERTIFIED`.
If any remain FAIL, certification stays REJECTED (fail-closed, by design) — capture the failing gate evidence.

## Step 4 — provenance close-out
Per the ledger's trailing-refresh protocol: the new evidence commit consumes `378ee830` as parent; add its freeze
refresh commit after the live evidence lands. Large XODR/runtime artifacts stay uncommitted (sha256-anchored).

## Boundaries
- Do NOT edit any `.xodr` or certifier logic to make gates pass — only fresh evidence may flip them.
- `run_n_certify.py` semantics are frozen; this runbook only *drives* it.
