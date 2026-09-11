# F5 Elevation Solver vs. Live Seam Repair

## Result

**Do not integrate F5 into stage 08.** This is a governed negative result on
the current pinned map-of-record, not a revision of the historical F5 result.

`repair_true_zseams` is a third implementation, not the historical F6
quadratic-blend writer. It nevertheless has the same local/per-seam character:
it sequentially repairs only ordinary road-to-road issues, adjusts `a`,
rederives `b`, and rechecks up to five times. F5 instead solves a complete
road-link graph, applying a constant per-road offset to `a` while preserving
`b/c/d`.

## Same-Input Comparison

All three arms used byte-identical source copies of the pinned map
`2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`.
The source itself was hashed before and after and was unchanged.

| Arm | Links | Ordinary links | Junction connector links | Max dz | >0.5 m | Runtime |
|---|---:|---:|---:|---:|---:|---:|
| Source | 45,178 | 0 | 45,178 | 3.473778 m | 922 | n/a |
| F5 graph relaxation | 45,178 | 0 | 45,178 | 3.473778 m | 922 | 12.634 s |
| Live `repair_true_zseams` | 45,178 | 0 | 45,178 | 3.473778 m | 922 | 119.084 s |

At the historical 5 m bound, every arm has zero links over threshold. The live
checker reports zero ordinary issues before and after and changes zero roads;
this is intentional because all measured links are junction connectors.

F5 reports one connected component and 32,208 nominal road offsets, but its
largest offset is only `4.999790636436852e-07 m`; its canonical seam metrics do
not improve. There is no current-map evidence that adding a map-wide F5 mutation
would solve the 922 junction-connector reference-line differences safely.

## Integrity Checks

The corrected preservation validation passes: road count, road links,
plan views, lanes, junctions, elevation segment counts, and each segment's
`s/b/c/d` values are unchanged. Only elevation `a` is eligible to vary. The
raw candidate and source map remain outside the repository; their paths and
SHA-256 digests are in the adjacent JSON report.

The first raw comparison's structural digest included serializer whitespace.
That evidence defect was corrected in
`compare_elevation_seam_repairs.py` and revalidated without rerunning a map
repair. Its numerical measurement and raw-artifact hashes are preserved, and
the corrected standalone validation is the authority for the preservation
claim.

## Boundary

The historical 2026-08-03 F5 result remains frozen and valid only for its F4
candidate. Its legacy seam helper assumes predecessor targets end and successor
targets start, whereas this comparison follows each link's declared
`contactPoint`. This report does not modify historical evidence or claim that
the historical result generalizes to the current map.

No pipeline wiring, map-of-record content, CARLA process, or CARLA RPC was
used or changed.
