# C35 - GAP-018 SUMO ParamPoly3 Tangent-Reversal Repair

**Status:** PASS - offline candidate only; not promoted and not live-CARLA tested.

## Scope and Provenance

* Base: `f195ba0b5d6df3f085573c5e996ff9d0f11a975f`
* Implementation: `db6a538973aebb12b80ec38f304075ab0413d80e`
* Input map-of-record SHA-256:
  `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`
* Detached candidate SHA-256:
  `e2f2cd77fdd5359e539433869f0a5ac25e1ef0115ffc467cd43245424ca8de68`

The map of record was read from its pinned campaign path and never modified.
All candidate files are under
`D:\carla-control-suite-experiments\gap-018-tangent-reversal-20260909`.
No CARLA process, RPC, or runtime validation was started.

## Root Cause

Road `45622`, geometry pair `60 -> 61`, has a position gap of
`3.939102e-07 m` and a heading difference of `179.9999999187 deg`.
The preceding normalized `paramPoly3` has `bU=1.85997989`,
`cU=-1.45592098`, `dU=0`, and its `du/dp` root is
`0.6387640248167864` within `[0, 1]`.

Historical regeneration shows that the pair first appears unchanged in stage
`02_sumo_fixed`; it is absent from the sanitized precursor and survives every
later stage.  Stage 02 invokes local SUMO `netconvert` with
`--geometry.remove true`; unsafe heading-smoothing flags were disabled in the
governed settings.  Re-running netconvert with `--geometry.remove false` did
not remove the numerical defect: the same near-180-degree pair appeared as
road `47183`, geometry `60 -> 61`.  Global SUMO conversion settings were not
changed.

## Repair Contract

`parampoly3_tangent_repair` identifies only candidates meeting all conditions:

1. a `paramPoly3` whose `du/dp` changes sign within its declared domain;
2. a direct successor with endpoint position gap at most `0.2 m`;
3. a wrapped tangent discontinuity of at least `170 deg`.

For an eligible pair, it solves a deterministic five-segment S-turn.  Each
segment is represented by a supported `paramPoly3` cubic approximation of a
constant-curvature arc, with less than a 90-degree turn.  The replacement
preserves the original pair's combined `s` span, start pose, endpoint pose,
and endpoint tangent.  It is committed only if all internal boundaries are
continuous and its sampled peak curvature does not exceed that of the source
pair.  Otherwise the original XML is preserved with a diagnostic record.

The road-45622 candidate reduced peak sampled curvature from
`3.8385058066 1/m` to `2.2036385580 1/m`; endpoint error is
`6.558460e-12 m` and endpoint-heading error is `2.524647e-12 rad`.

## Offline Results

| Check | Before | Candidate | Result |
|---|---:|---:|---|
| Exact defect candidates | 1 | 0 | PASS |
| Heading-only discontinuities | 82 | 81 | PASS |
| Roads / junctions / total road length | 32267 / 3561 / 1489145.5752454493 m | unchanged | PASS |
| Strict XODR errors / warnings | 0 / 134 | 0 / 134 | PASS |
| Offline acceptance | valid | valid | PASS |
| New isolated components | 0 | 0 | PASS |

The repair was run twice in memory from the same input.  Both the XML bytes
(`e1476b3d9470e328733821f747b865b3e05046a846b7f518fc60959b50812991`)
and report records matched exactly.

Verification after the implementation commit:

* Focused geometry suite: `94 passed`.
* Full offline suite with CARLA disabled: `1427 passed, 1 skipped` in
  `173.27 s`.

## Boundary

This is a targeted repair for the one confirmed full defect signature, not a
claim that all 82 pre-repair heading-only discontinuities share the same cause.
No map candidate was promoted.  Live CARLA compatibility remains `NOT_RUN`.
