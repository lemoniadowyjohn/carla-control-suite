# Roundabout Reconstruction V2

V2 is an opt-in, offline candidate subsystem. It is not wired into release profiles and does not
modify the map of record.

## V1 problem

V1 detects short/curvy one-way roads, estimates a center from first geometry points, averages a
radius, emits one perfect circular road and one lane, rewrites connections best-effort, uses an
angle-based contact point, and approximates elevation from coefficient `a`. These shortcuts can
discard source topology and make ambiguous attachments look valid.

## V2 candidate behavior

Detection is ordered from explicit OSM `junction=roundabout|circular` markers to junction topology
and then curved geometry. Each candidate has a typed source identity, confidence, reason, and sorted
IDs. The sampler evaluates complete `line`, `arc`, `paramPoly3`, and `poly3` geometries at deterministic
spacing and returns position, heading, curvature, road ID, and `s`.

Anchors use the connection's explicit endpoint and sampled endpoint pose. They do not infer
`contactPoint` from polar angle. Existing driving lane IDs are retained with source/confidence
provenance, and the universal `-1` to `-1` lane-link sentinel is rejected. Elevation is evaluated as
`z=a+b*ds+c*ds^2+d*ds^3` with derivative `b+2*c*ds+3*d*ds^2`; duplicate or non-monotonic records
are rejected by the validator.

Circle fitting uses all samples and reports residual diagnostics. A residual above the configured
threshold selects `SOURCE_PRESERVED_NON_CIRCULAR`; V2 does not force an ellipse or asymmetric source
geometry into a circle. `reconstruct_transactional()` analyzes a deep copy and returns diagnostics,
leaving the authoritative root unchanged. `reconstruct_ring_transactional()` builds a segmented ring
from source-backed anchors, validates the complete clone, and returns the original root on failure.
Segment roads use endpoint-constrained normalized paramPoly3 curves, deterministic closed road links,
and preserved lane IDs. `build_junction_lane_links()` emits only validated source/target references.

## Deliberate candidate limits

The candidate does not yet replace the pipeline release-path V1 call site, perform junction-wide
approach mapping without caller-supplied anchors, or run against materialized Ingolstadt/Munich map
payloads. Those are explicit blockers, not silently treated as passing production behavior. No release
profile enables V2, no CARLA process is started, and no pinned artifact is changed.
