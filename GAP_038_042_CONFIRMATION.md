# GAP-038 through GAP-042 Confirmation

Source authority: remote `stabilize/research-release-20260905` at
`f195ba0b5d6df3f085573c5e996ff9d0f11a975f`.

* **GAP-038 CONFIRMED.** The width-policy repair path flattened any changed
  width to `a=target,b=0,c=0,d=0`. It now preserves a finite, positive existing
  polynomial and still repairs the known 6 m placeholder or invalid values.
* **GAP-039 CONFIRMED.** `_build_adjacency()` used one unprefixed keyspace for
  roads and junctions. It now uses `road:<id>` and `junction:<id>` keys and
  converts road membership back to the public report IDs.
* **GAP-040 CONFIRMED.** Signal references were validated against lane IDs
  across the whole map. They are now checked against the active lane section
  of their own road at the reference `s`; unscoped references fail closed.
* **GAP-041 REFUTED.** No `ELEVATION_FALLBACK_POLICY` or `lenient` override
  exists in the inspected release-base settings or pipeline modules. No fix was
  applied and no production policy was invented.
* **GAP-042 CONFIRMED.** Tile bounds were cached by road ID only. The cache key
  now includes a SHA-256 digest of the road's planView XML, preventing reuse
  across different geometry for the same road ID.

Focused verification: 27 tests passed (`test_confirmed_gap_batch.py`,
`test_map_hygiene.py`, and `test_traffic_light_signals.py`). Full repository
verification remains incomplete in this sparse worktree because unrelated
modules are intentionally absent. No CARLA process or RPC was used.
