# 05 — Coordinate Contract Decision

**STATUS: PENDING** — filled after **C44V01** returns (`CRS_CONTRACT_READY` or a BLOCKED/FAIL verdict).
The projected CRS MUST be parsed from the XODR `<geoReference>` / OSM2World config — never assumed (rule 4.5).
No free-form affine that hides a wrong CRS; allowed transforms = projection · origin offset · axis conversion ·
unit conversion · rigid rotation/translation · vertical offset. Vertical reported separately; no PASS if datum unknown.
Couples to AG04 (stage-2 projected CRS + stage-3 vertical datum both currently UNKNOWN).
