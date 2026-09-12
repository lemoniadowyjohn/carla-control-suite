# Architecture

`ultimate_pipeline.main_pipeline` owns pipeline implementation. `ultimate_pipeline.cli` is the
user-facing command surface and exposes the `up` console script. `ultimate_pipeline.run_pipeline`
is a backwards-compatible shim only.

The pipeline stages transform pinned OSM inputs into OpenDRIVE, then quality, topology, CARLA,
sensor, domain-gap, and experiment modules produce governed evidence. `tools/` contains explicit
research exporters and audits. `reports/` contains generated evidence and health packets; `submission/`
contains frozen thesis material.

No module may mutate `builtins.print` at import time. JSON commands write JSON only to stdout.
CARLA-dependent checks are separated from offline checks and must record runtime identity and
capture-manifest hashes.
