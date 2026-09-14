# HH: OSM Road-Link Topology Cross-Check

## Decision

`NOT_WIRED (advisory)`.

The implementation is a deterministic, read-only tool.  It was not added to
Stage 4 because its first governed full-map execution covers too little of the
map to serve as useful live pipeline telemetry and has a high disagreement
rate in that small subset.

## Governed Inputs

- XODR map of record: `ingolstadt_perception_map_of_record_20260905_202847.xodr`
  - SHA256: `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`
- Pinned OSM: `ingolstadt_authoritative.osm`
  - SHA256: `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f`

Both input SHA256 values were identical before and after the audit.

## Probe Result

The OSM endpoint index contains 17,200 highway ways and 15,566 undirected
endpoint-adjacency edges.  The canonical spatial correspondence engine found
only 134 eligible HIGH/EXACT road associations against 32,267 XODR roads.  Of
the resulting boundaries, 28 were checkable: 15 agreed and 13 disagreed.
Another 226 were explicitly incomplete because either the adjacent OSM way had
no high-confidence XODR association or the declared XODR junction link could
not be resolved through its bounded connector chain.

This is evidence about correspondence coverage and conversion representation,
not proof that the 13 differences are map defects.  The check neither changes
nor certifies road links, junctions, lane links, or map acceptance.

## Determinism

Two independent read-only executions produced byte-identical reports:
`472da39ddd1a938cd0e6baef1ad50c9230c7c4a3c138adf3c9d587e36dac5a0b`.

## Verification Boundary

The checker tests direct road links, OSM/XODR orientation reversal, a bounded
junction connector path, disagreement handling, incomplete neighbour
correspondence, and CLI read-only behavior.  Full offline pytest completed
with `5951 passed, 82 skipped, 0 failed`.  No CARLA process or RPC was used.
