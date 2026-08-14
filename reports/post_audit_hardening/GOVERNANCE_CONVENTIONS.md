# Governance Conventions (documented from existing evidence)

Source of truth for the non-obvious conventions in this repo. All items below are
documented from existing evidence or committed prompts - nothing here is new policy.

Cross-reference: [SUMMARY_R17_G19.md](20260813T075853Z_N_CERTIFICATION/SUMMARY_R17_G19.md)
(branch fix/post-audit-phase-e-junctions-roundabouts-20260803, commit 378ee830).

## 1. Large XODR artifacts: uncommitted, sha256-anchored in evidence

- Candidate / runtime XODRs are ~78-81 MB each. Governance forbids staging large
  datasets, so they are **intentionally uncommitted**.
- Integrity is anchored by sha256 **inside evidence JSON string values** in
  `reports/post_audit_hardening/<RUN_ID>_N_CERTIFICATION/*.json`, in the form
  `<name>_sha256=<hex>` (e.g. `runtime_sha256=9630d9f6... length=81301200`,
  `rep_sha256=80ebb005...`). The digests live in evidence strings, not JSON keys.
- How a verifier checks a local copy: re-fetch the artifact, then confirm
  `sha256(local copy) == recorded digest`. Automated check:
  `tests/unit/test_evidence_sha256_anchors.py` parses every embedded anchor,
  asserts 64-char lowercase hex form, verifies any locally-present referenced
  artifact against its recorded digest, and SKIPs artifacts absent locally
  (the 78-81 MB XODRs are typically absent from the committed tree).
- If a local artifact exists but its hash no longer matches the recorded digest,
  that is a drift signal and must be reported, not silently re-anchored.

## 2. scripts/ and probe logs: scratch / untracked by convention

- `scripts/` probe utilities (opendrive_gen_probe.py, opendrive_gen_watch.py,
  analyze_xodr_s_length.py, etc.) and probe run logs
  (`reports/post_audit_hardening/*_PROC_SMOKE/`, watch logs, watch JSON output)
  are **scratch / untracked by convention** - not committed, not drift-guarded.
- Promotion of a probe to production is an architectural decision (Claude's),
  not a mechanical one. When promoted, a probe must be **mirrored** into
  `submission/infrastructure/ultimate_pipeline/` and **hash-registered**
  (added to the drift-guard CRITICAL_MIRRORED_FILES list), exactly as done for
  `core/opendrive_gen_diagnostic.py` (R17/G19).

## 3. Canonical vs submission mirror policy

- `ultimate_pipeline/` is the **canonical** tree; the governed release tree is
  `submission/infrastructure/ultimate_pipeline/` (a mirror).
- The two trees must stay in sync; byte-level drift between them is tracked in
  `MIRROR_DRIFT_INVENTORY.md` / `.json` (read-only inventory, not a fix).
- The drift-guard test (`tests/phase_q/test_duplicate_module_drift.py`,
  `CRITICAL_MIRRORED_FILES`) protects only the **load-path-critical set**
  (carla loader, hash gate, diagnostic, identity guard, compat check,
  load-into-CARLA tool). Any edit to a guarded file must keep both sides
  byte-identical, or the guard test fails.
- Full drift status (all mirrored pairs, guarded or not) lives in the inventory;
  reconciling drifted pairs is a Claude decision.

## 4. Certification state (context, not policy)

- Phase-N certification is `PHASE_N_CERTIFIER_REJECTED` by design (13 pass /
  7 fail, fail-closed) pending a live CARLA evidence re-collection. The 7
  failing gates are stale-anchor failures (G2 pins the superseded candidate
  sha `80ebb00`; G5/G6/G7/G14/G15/G18 reference stale runtime evidence).
- Verdict logic is not to be modified offline; flipping gates requires fresh
  live evidence on the pinned runtime sha (`6bac3570` candidate, commit
  `10033a16`) per SUMMARY_R17_G19.md section 4.