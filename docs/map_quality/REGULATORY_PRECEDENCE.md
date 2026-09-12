# Regulatory Metadata Precedence

Position-sensitive OSM metadata is applied only after an `EXACT` or `HIGH`
spatial OSM-to-XODR correspondence result. `AMBIGUOUS` and `UNMATCHED` source
ways do not write map semantics.

The Stage 4 ordering is intentional and does not establish authority by call
order:

1. Existing XODR lane `speed` and `turnMarking` values are retained. Their
   source provenance is not recoverable in every historical artifact, so a
   later writer may only fill an absent value.
2. An explicit, HIGH/EXACT-associated OSM regulatory speed sign replaces only
   the identifiable `RealismModule` heuristic object (`id="speed_<road-id>"`).
   It never removes an unprovenanced third-party object.
3. A source regulatory sign, turn-lane value, or maxspeed with no qualifying
   correspondence is skipped. Legacy name matching is compatibility-only and
   is not a Stage 4 fallback.
4. Topology-inferred traffic lights are not ground-truth regulatory evidence.
   Their placement is governed separately until mapped OSM signal positions
   are available and validated.

This is a count/association policy, not a claim that every generated sign is
spatially correct. The correspondence report records eligible and conflicting
roads for each run.
