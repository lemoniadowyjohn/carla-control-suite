# Roundabout Reconstruction V2 Baseline Audit

Baseline source is `f195ba0b5d6df3f085573c5e996ff9d0f11a975f`, remotely verified on
`stabilize/research-release-20260905`. MQ-A artifacts and the explicit re-baseline authorization
are copied from the clean architecture worktree.

V1 inspection confirms: junction-local short/curvy/one-way detection; center from first geometry
points; mean-radius estimation; one perfect 360-degree arc; one circulating lane; possible `-1` to
`-1` lane-link fallback; angle-derived contact points; coefficient-`a` elevation approximation;
best-effort incremental mutation; duplicate detection/tagging in `roundabout_rebuilder.py`; and
invocation from stage 04 before later geometry/lane work. Release settings keep reconstruction off.

Existing static validators include junction integrity, lane-link, geometric/elevation continuity,
component reachability, strict OpenDRIVE, and CARLA compatibility checks. Full map-dependent metrics
are explicitly unavailable in this sparse checkout and are not inferred.
