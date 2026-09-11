# Native Signal Enrichment Investigation

## Decision

`ENABLE_NATIVE_SIGNAL_ENRICHMENT` remains disabled. No settings, release profile,
pipeline wiring, map-of-record, or frozen evidence was changed.

The historical Phase-H evidence is useful provenance, not a basis to enable the
feature now: the mandated fresh reproduction against the pinned map failed before
matching or writing. The failure is strict and expected to be fail-closed:
`no_frame_matches_osm_source` from the F1 CRS contract.

## Fresh Reproduction

The input map and an external candidate both hash to
`2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`.
`apply_native_signal_enrichment` stopped after 25.824 seconds in
`OSMSignalExtractor` initialization. It made no writes.

Raw reproduction evidence:
`D:/carla-control-suite-experiments/native-signal-enrichment-v1-20260911/20260911T112500Z/NATIVE_SIGNAL_FRESH_REPRODUCTION.json`
(`daf530b7637c54c7f09ccdc265593825ee6e4be03dbfa511d34c752b6d5d8af0`).

## Existing Signal Layer

The current map has 21,163 existing signal elements. Running Phase H's own
`audit_clean` against that layer reports `clean: false`: all 21,163 are unknown
to its governed type/prefix/provenance scheme and 7,815 spatial duplicates are
reported. This is an independent second incompatibility. It means repairing CRS
alone would not justify enabling Phase H: its audit needs a governed migration of
the existing layer or a narrowly tested scope boundary.

Raw audit:
`D:/carla-control-suite-experiments/native-signal-enrichment-v1-20260911/20260911T112500Z/EXISTING_SIGNAL_LAYER_AUDIT.json`
(`5ad2be71d9b30344cd5a06aa60c64a2ca8f97cace0d8066d29a5d376678f8bf3`).

## Gate And Overlap

The opt-in gate was introduced in `a67824966`; the examined gate history did not
state a reason for the default-off decision. The absence of a documented reason
does not establish that it was safe to enable. The two current, reproducible
blockers above do establish that it is not safe today.

The requested Stage-4 overlap test was not run. Native enrichment did not reach
`remove_legacy_speeds` or any writer, so a claim about ordering or deduplication
would be unsupported. The source map's observed counts are 34,285 lane speed
elements, zero regulatory-sign objects, 21,163 signal objects, and zero turn-lane
vectors.

## Verification Boundary

`python -m pytest -q tests/unit/test_native_signal_enrichment.py` passed (1).
The full offline suite was intentionally not run after the prompt's mandatory
fresh-reproduction stop condition. CARLA was not started or contacted.
