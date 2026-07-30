# 05 — Coordinate Contract Decision

**STATUS: BLOCKED_MISSING_METADATA** — C44V01 parsed the historical `submission/results/structural_gap_run11/auto_aligned_rigid.xodr`
geoReference and rigid-scale alignment, but the current repository still lacks authoritative OSM identity, OSM2World,
Blender, FBX, and vertical-datum metadata required for a contract-ready pass.
The projected CRS was parsed from XODR `<geoReference>`; no free-form affine was introduced.
Allowed transforms remain projection · origin offset · axis conversion · unit conversion · rigid rotation/translation ·
vertical offset. Vertical is still reported separately, and no PASS is possible while the datum remains unknown.
Couples to AG04 (stage-2 projected CRS + stage-3 vertical datum remain unresolved for the new campaign).
