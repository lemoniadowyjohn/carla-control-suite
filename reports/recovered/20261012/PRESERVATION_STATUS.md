# Preservation Status Corrections — 2026-10-12

Corrections of record accompanying `evidence/thesis-current-recovery-20261012`.
These supersede earlier status wording that overstated verification.

---

## 1. Topology — fresh regeneration NOT verified

The topology "fresh admission" **did not complete a full fresh pipeline regeneration**.
Existing historical Stage-7/Stage-8 artifacts were used after the fresh pipeline
exceeded its time allowance. Those historical artifacts must **not** be described as
fresh pipeline output.

```
FRESH_TOPOLOGY_REGEN_VERIFIED=false
TOPOLOGY_STATUS=FRESH_REGEN_ADMISSION_PENDING
```

## 2. GAP055 — CI has already executed

The GAP055 CI run **did execute**. The bulk suite was red, but the same five
governance mutex-contention tests also fail on a pristine base — i.e. the failures
are pre-existing suite failures, not regressions introduced by the GAP055 change.

Preferred status:

```
GAP055_STATUS=FIX_VALIDATED_CI_EXECUTED_PREEXISTING_SUITE_FAILURES
```

rather than `LOCAL_PASS_CI_PENDING`, unless a further clean CI run is explicitly
required by policy.

## 3. GAP026 — current known residual, not a closure substitute

```
513 total
192 severe distance
  0 severe angle
  0 unexplained
```

These values describe the current known residual only. They are **not** a substitute
for the still-pending fresh regeneration in section 1.

## 4. RQ2 — commit af90dd91

`af90dd91ababd646f59ea7dc82e0b196753acb67`
("Merge rq2-authority: add registry-resolved RQ2 metric authority layer") was
previously reported as contained in zero remote refs. Re-proven during this task and
found **already preserved remotely** at the identical SHA via
`origin/rescue/rq2-authority-merge-af90dd91-20261012`. No rewrite, cherry-pick,
amend, or rebase was performed.

## 5. Byte-fidelity note

Two recovered artifacts (`GAP026_FINAL_CLASSIFICATION.md`,
`GAP055_SHARED_TREE_CONTAMINATION_INVENTORY.txt`) were line-ending converted by
Git's default `autocrlf` on first staging. This was detected by comparing
`git hash-object --no-filters` against the staged blob, restaged with
`core.autocrlf=false`, and re-verified as byte-identical. This is the same CRLF
class of defect already documented in this repository's `.gitattributes` for
`INPUTS_MANIFEST` and `aggregate_stats.json`. Committed blobs match the original
local bytes exactly; the SHA256 values in `EVIDENCE_INDEX.json` are authoritative.