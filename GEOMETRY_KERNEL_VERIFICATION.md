# Geometry Kernel Verification

The canonical evaluator is `ultimate_pipeline.geometry.opendrive_geometry_kernel`.
It supports line, constant-curvature arc, clothoid/spiral, poly3, and paramPoly3
with both `pRange=normalized` and `pRange=arcLength`. All sampling is deterministic.

The oracle tests are in `tests/unit/test_geometry_kernel.py`. They use hand-derived
fixtures for line endpoints/projection, quarter-circle pose, polynomial centerline,
both paramPoly3 parameter conventions, and a linearly varying-curvature clothoid.
The spiral integrator uses fixed-step RK4 with a maximum step of 0.25 m; its
determinism and expected curvature are tested. It never silently falls back to a
straight line. Projection is a densified segment projection with a documented
spacing argument and is intended for bounded correspondence use.

`geometry_validator.py` now obtains missing geometry origins from the previous
primitive's canonical endpoint. The regression test uses an arc and would fail
under the former unconditional line displacement.

The remaining consumers are intentionally not migrated in this prompt:

* `crosswalk_writer.py`: has an existing curve-aware matcher; migrate after comparing
  projection tolerances and reports against this kernel.
* `structure_classifier.py`: its current poly3/spiral straight-segment fallback is
  unsafe; migrate in a dedicated consumer commit after the spiral error contract is
  reviewed.
* `topology/roundabout_v2/core.py`: has a local sampler; migrate after preserving its
  structural-signature behavior in a focused compatibility test.

This is offline-only. No CARLA process, RPC, map-of-record, or frozen evidence was used.
