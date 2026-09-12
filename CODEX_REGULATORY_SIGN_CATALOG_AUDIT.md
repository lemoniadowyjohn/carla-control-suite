# Regulatory Sign Catalog Audit

The current sign writer is called and has source records, but a bulk
`SIGN_TABLE` expansion is not an admissible repair. The pinned source has 529
ways carrying 41 raw sign values; none match the vehicle-oriented entries
already supported by the writer. Most originate on paths, footways, cycleways,
service roads, or tracks.

Spatial correspondence produces only six eligible XODR roads, all for
`de:244.1` pedestrian-area variants. The source has no eligible evidence for a
speed, stop, give-way, or priority sign that the writer can represent without
inventing a CARLA/OpenDRIVE object meaning.

The outcome is `NO_CATALOG_EXPANSION`. Compound access/no-entry tags require a
separate lane-applicability and access-restriction contract, not conversion to
generic visual signs.
