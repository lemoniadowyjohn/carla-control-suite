# R01 — Process Integrity Correction (C0 gate restoration)

> Run ID: `20260808T000000Z_C0_REMEDIATION` — Branch: `fix/post-audit-phase-e-junctions-roundabouts-20260803`
> External verdict: `CLAUDE_SEMANTIC_WRITE_CONTRACT_NEEDS_FIXES`

## 1. Finding (external C0 review)

Implementation, governance, promotion and release-closure changes were executed
**before** the Claude C0 acceptance gate. Concretely on this repository:

| commit | content | problem |
|---|---|---|
| `2ec8927a` | Stage I-N enrichment producer + tests | implemented pre-C0 (kept as code, re-verified under R2/R9) |
| `b9d51fe7` | govern + promote + offline verdict (N19, manifests, PQ closure) | promotion pre-C0 |
| `3eede5b4` | promotes `ingolstadt_perception_final.xodr` (LFS) | promoted pre-C0 |
| `74fb5b4d` | N22/N23 evidence + perception governed payload | closure evidence pre-C0 |

None of the above is release authority. The promoted binary carries a
misleading authoritative name (`ingolstadt_perception_final.xodr`).

## 2. Independent integrity break discovered during quarantine (this run)

While inventorying artifacts the on-disk file
`reports/post_audit_hardening/20260807T000000Z/perception_governed/governed_payload.xodr`
was found NOT to match the payload recorded by its `Q03` manifest:

| field | declared (Q03) | on disk |
|---|---|---|
| sha256 | `719eec3ec169…a392ac21` | `a7b319db6627…af50a30f` |
| length | 80,996,355 bytes | 82,589,778 bytes |

The on-disk file is a near-copy of the candidate, not the governed payload
(compare `82,589,778` ≈ 82,589,796 candidate bytes). This is recorded in
`R00_PRE_GATE_PROVISIONAL_ARTIFACTS.json` (`payload_declared_vs_disk`). The
parent's `governed_payload.xodr` **does** match its Q03 declaration (`3f7370ef…`).

**Consequence:** the pre-C0 "perception governed payload" must never be used as a
release payload. This failure is itself proof that pre-C0 closure was not sound.

## 3. Correction actions (all forward, auditable; no history rewrite)

1. **Quarantine inventory** → `R00_PRE_GATE_PROVISIONAL_ARTIFACTS.json`
   (10 artifacts, each `PROVISIONAL_PRE_C0`, `release_authority=false`).
2. **Rename misleading promoted binary**:
   `campaigns/.../candidate/ingolstadt_perception_final.xodr`
   → `provisional_pre_c0_ingolstadt_perception.xodr` (content unchanged; same LFS object).
3. **Campaign manifest**:
   - removed `perception_candidate_xodr` and `perception_governed_payload` from
     the authoritative top-level object;
   - `readiness_state` → `REVIEW_RESTORED_PENDING_CLAUDE_C0`;
   - acceptance flags all `false` (C0, C1, perception candidate, final closure);
   - added provenance-quarantine pointer + hard authority rule referencing R00.
4. **Release closure** (`PQ_FINAL_RELEASE_CLOSURE.json`):
   - closure state → `PENDING`; all acceptance flags `false`;
   - prior verdicts kept as **historical/provisional** records, not authority.
5. **Corrective commit**: `Restore C0 gate and quarantine provisional perception artifacts`
   (SHA recorded below after commit).

## 4. Hard authority rule (violations are fail-closed)

```
A_IFACE_RULE_PRE_C0:
  any artifact bearing status PROVISIONAL_PRE_C0 may not serve as:
    - release authority
    - governed/promoted candidate
    - load payload
    - semantic parent
  until CLAUDE_SEMANTIC_WRITE_CONTRACT_ACCEPTED (C0) is recorded.
  A validator must reject loads referencing such artifacts (see M01 regression).
```

## 6. Resulting state

- C0 accepted = **false**; C1 accepted = **false**; perception candidate accepted = **false**; final perception closure = **false**
- Authoritative manifest: no perception candidate / governed payload fields
- Recommended candidate (not yet built): to be rebuilt after C0 acceptance from
  the re-frozen 3,467-signal semantic parent (`candidate_g_semantic_enriched.xodr`,
  sha256 `8b60d8f4…`).

## 8. Corrective commit

Committed at the end of this stage (see Git log, single forward commit).