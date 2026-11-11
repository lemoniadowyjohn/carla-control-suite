# Independent acceptance checklist for SCI-CORRECT-003

To be run by a reviewer from a different model family before any of these documents is committed.
A tick requires an executed command and its output.

## Addendum 3
- [ ] `GAP_REGISTER_ADDENDUM_3_PROPOSED.json` parses, and `evidence/build_addendum3.py` regenerates it
  byte-for-byte from addenda 1 and 2.
- [ ] Re-derive `register_state_after` independently: 25 / 19 fixed / 5 open / 1 blocked.
- [ ] `git grep -E "GAP-0(8[0-9]|9[0-9])"` over all refs finds nothing before allocation.
- [ ] Addenda 1 and 2 are byte-unchanged; addendum 2's sha256 is `5f59fc60…`.
- [ ] GAP-080 says "not claimed undrivable", and its status is open.

## Input lineage
- [ ] Open `run_manifest.json` of run `20261007_214826_524342` and confirm that
  `inputs.INPUT_XODR.sha256 == 370abbbb…`.
- [ ] Confirm `sha256(01_sanitized…) == 370abbbb…`.
- [ ] R-13: read `stage_06_links.py` at `22cf39ab` (lines 237-240, ~296) and
  `stage6_containment_runtime.json` (mode, input_xodr, planview_output). Confirm that
  `sha256(03) == sha256(05)`.

## Lane-level numbers (requires the local or archived stage files)
- [ ] Re-run `evidence/lane_centre_continuity_v2.py` on 05 (sha256 `45c52059…`) and reproduce:
  - 23,406 laneLinks;
  - U-turn class 3,947;
  - 3,696 with entry gap > 0.5 m;
  - median 0.7467 m / 26.565°.
- [ ] **Independent second implementation** of the lane-centre metric (O13 or other), agreeing
  within a stated tolerance. Until this is done, all lane-level claims stay LOCAL_REPRODUCED.
- [ ] Spot-check 5 laneLinks by hand (connector 51810 is one) against the raw XML.

## RQ answers draft
- [ ] Every number in `RQ_ANSWERS_REVISED_DRAFT.md` matches its source file. Check at least the hull,
  bbox and whole-map values, the 5 RQ4 seed values, and the C15 aggregate signature.
- [ ] No historical value has been altered; every correction is marked [corrected].
- [ ] RQ3 and RQ5 contain no numbers.

## RQ4 specification
- [ ] No p-value or significance statement appears anywhere.
- [ ] The sampling unit is spatial blocks; seeds are not pooled; the null is defined.

## Publication (operator)
- [ ] The operator approves publication: a docs-only branch, with no edits to existing reports.
