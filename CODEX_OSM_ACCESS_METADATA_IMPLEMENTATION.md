# OSM Access Metadata Implementation

## Scope

This change records matched OSM `access`, `motor_vehicle`, `vehicle`, `psv`,
and `bicycle` tags as versioned road-level OpenDRIVE `userData` vectors. It
does not modify lanes, lane counts, lane links, road links, routing, or the
map-of-record.

The writer uses the native OSM-to-XODR projection contract, exact road-name
agreement, and direction-independent curve distance. A candidate is accepted
only when its mean XODR-sample-to-OSM-polyline distance is at most 2 m and at
least 90 percent of XODR samples lie within 2 m. Unmatched and ambiguous
associations are omitted rather than guessed.

## Governed Offline Candidate

The source map remains SHA-256
`2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`.
The separate candidate is SHA-256
`9e9ff162628f1f1887ba5e132115d7ad7337072bded1beedf4f9da072d9c36e5`.

The run processed 2,041 eligible OSM ways in 26.857 seconds. It accepted
2,010 associations across 1,998 roads and wrote 2,010 provenance vectors:
1,769 `EXACT` and 241 `HIGH`. The candidate preserved all structural counts,
the lane signature, and the road-link signature. The machine-readable record
is [CODEX_OSM_ACCESS_METADATA_IMPLEMENTATION.json](CODEX_OSM_ACCESS_METADATA_IMPLEMENTATION.json).

## Verification Boundary

Focused tests passed (`8 passed`), as did module compilation and the Stage 4
import check. The full offline suite was not run in this sparse artifact
worktree, whose ignored large integration artifacts are intentionally absent.
No CARLA process, RPC, map promotion, routing behavior, or frozen evidence was
changed. Applying access restrictions to routing remains a separately governed
policy and implementation task.
