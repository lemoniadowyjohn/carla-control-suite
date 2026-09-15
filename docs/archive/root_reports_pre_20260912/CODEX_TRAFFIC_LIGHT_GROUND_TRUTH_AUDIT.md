# Traffic-Light Ground-Truth Audit

The pinned Ingolstadt OSM source contains no `highway=traffic_signals` feature
on a node, way, or relation and no `traffic_signals:direction` tag. It contains
44 `crossing=traffic_signals` ways. Those ways describe pedestrian-crossing
control, not the location, facing direction, or lane applicability of a road
traffic light.

`TrafficLightInferer` currently has no OSM source input and emits 21,163
topology-inferred traffic-light objects/signals in the pinned XODR. Replacing
or scoring those locations against the 44 crossing attributes would create a
false ground-truth claim. This task is therefore `INCOMPLETE`, not a code
change, until a governed source with road-signal semantics is available.
