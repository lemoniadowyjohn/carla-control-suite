# G0 — Phase F handoff and freeze

- run_id: `20260803T190000Z`
- verdict: **PHASE_G_INPUT_ACCEPTED**

## Input candidate (F7-approved)

- path: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\post_audit_hardening\20260803T160000Z\candidate_f5_bounded_offsets.xodr`
- byte sha256: `ac2513e815b22e3a691a9d5f7640c4164b56ee0f53813b9067f0581396e369ba`
- canonical semantic sha256: `6fbe69777c5bdaa922a9e5d3943644e69089783ed8e3543c2a6b23c09de48ec1`
- roads: 32710

## Protected identity hashes

| domain | sha256 |
|---|---|
| planView | `20a8c59eaa112daac3e1b8fdae519037ff1a09662e48f83eeb4083e2aef345e2` |
| road length | `d9cac90beff8911020398bdec7a213eddf7d0db7dff34e7091d655c4bef00cd7` |
| elevation profile | `44b2c6701c3c492355978c7d1029dbc7d8da6f80f322cbbe48370b7bac9b6228` |
| road link | `df42d88ac61abf7b145065ae951c596e0bc2fa2163ad947b00c587cb232c41fd` |
| junction structure | `20a70cfcee1f38e7485d913fd818fc7aaa88777c98e2df9f0a1c27609b351785` |
| connector geometry | `418d4f665a0dff2ba1ee83e85584e76ffa84a0a4ec73d9385b84aa82d8a13754` |
| contactPoint | `541f8ea6af7f716b19767c451562ece9d87ba91da10c8f377bfc69d3d3c24052` |
| lane topology (G baseline) | `3547b06a2acd3106952b296fc16e266b9afc65b70a58bc3a6ed3bef02aff12b0` |

## Freeze cross-checks

- f7_evidence_verdict_verified: PASS
- f7_recorded_path_matches: PASS
- f7_recorded_sha_matches_byte_identity: PASS
- road_count_32710: PASS
- phase_e_freeze_record_validated_by_f7: PASS

Byte identity is line-ending tolerant: the F7 evidence recorded the working-copy CRLF sha while the LFS-stored blob is LF-normalized; the stored byte sha matches the recorded sha under LF normalization.  The lane-topology hash is the Phase G baseline and will be recomputed after every mutating subphase.