# Building Frame Alignment Evidence

This packet evaluates the pinned building source against the pinned
map-of-record using stable OSM-derived building object IDs.  It does not modify
either artifact.

`BUILDING_FRAME_ALIGNMENT.json` records a `PASS` for the coordinate-frame
contract: 5,680 shared building IDs have median displacement magnitude
`0.000001223 m` and p95 per-building displacement `0.000338287 m` after the
OpenDRIVE header offset is applied to the source projection.

The previously reported `1571 m` distance between the road-population centroid
and building-population centroid is not a coordinate-frame metric.  Roads and
buildings are different spatial populations and are not expected to share a
centroid.  The per-object audit supersedes that interpretation.

The report retains 18 individual source-to-output geometry differences above
`0.01 m`, with a maximum `10.551556 m`, plus 30 source-only and two
map-only IDs.  These are reported as `individual_geometry_drift`; they are not
evidence for applying a whole-map translation.  Their provenance and root
causes remain a separate bounded investigation.

Inputs:

* map-of-record SHA-256: `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`
* pinned buildings SHA-256: `f3e8200118845910e136b478a68bd6eb67b985fef6357b98f76ecc6f520e30f5`

No live CARLA process was started.  This is an offline source/serialization
contract only.
