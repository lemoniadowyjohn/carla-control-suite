# GG ParamPoly3 Baseline Audit

Base: `47d9c7b26167c47ae625dd2212bcb24eed75957c`.

The audit distinguishes a primitive type check from a calculation that turns a
non-arc geometry into a straight line. Only the latter is changed.

| File | Classification | Evidence and disposition |
| --- | --- | --- |
| `diagnostics/xodr_cropper_gps.py` | SAFE | Lines 208-215 explicitly sample `paramPoly3`; the arc branch at 273-278 only supplies arc curvature. |
| `domain_gap/elevation_gap.py` | SAFE | Lines 170-175 select arc, `paramPoly3`, then line sampling explicitly. |
| `domain_gap/geo_alignment.py` | SAFE | Lines 44-64 explicitly sample `paramPoly3` before line fallback. |
| `domain_gap/map_stats_xodr.py` | SAFE | Lines 239-281 explicitly calculate sampled `paramPoly3` curvature. The arc roundabout heuristic at 187-200 is classification-only. |
| `domain_gap_gnn/graph_builder.py` | BUGGY | Lines 120-131 derive every lane node's curvature features only from `<arc>` and assign zero when absent. This contaminates the RQ4 graph representation. |
| `experiments/rl_fuzzer.py` | SAFE | Lines 142-161 deliberately mutate only `<arc curvature>` records. It does not derive a pose or curvature for another primitive. |
| `geometry/lane_seam_checker.py` | BUGGY | Lines 22-57 return a straight-line sample whenever `geom.find("arc")` is absent. This is a tile seam validator, not merely a display helper. |
| `geometry/planview_smoother.py` | BUGGY | Lines 10-26 calculate terminal-anchor endpoints only for `<line>`; lines 65-88 suppress the anchor guard for a terminal `paramPoly3`, leaving the experimental mutator with an incorrect continuity decision. |
| `pipeline_stages/stage_06_links.py` | BUGGY | Lines 56-79 calculate predicted plan-view endpoint changes as a line unless the primitive is an arc. Stage 6 is contained read-only, but these diagnostics feed its governed report. |
| `quality/xodr_strict_validator.py` | SAFE | Lines 410-456 validate primitive cardinality and an arc's own finite curvature only; no endpoint or non-arc curvature is inferred. |
| `roadrunner/alignment.py` | BUGGY | Lines 46-83 samples every non-arc plan-view geometry as a line. These points drive alignment RMSE, heading, and scale evidence. |
| `tools/junction_connector_rebuild.py` | SAFE | Lines 73-79 classify primitive kind; endpoint calculations are delegated to `topology_repair._road_start_end`, which receives the dedicated correction below. |
| `topology/junction_connector_rebuild.py` | SAFE | Lines 12-17 and 52-63 use canonical kernel endpoint/pose calls. Its arc checks at 185-204 classify rebuild choices. |
| `topology/roundabout_rebuilder.py` | SAFE | Lines 36-43 use arc count only as a legacy roundabout heuristic. It does not calculate position, endpoint, or curvature from a non-arc primitive. |
| `topology/roundabout_reconstructor.py` | SAFE | Lines 42-74 use arc count and geometry-start headings only for legacy candidate classification. V2 source-aware detection is separately opt-in. |
| `topology/topology_repair.py` | BUGGY (utility hardening) | Lines 52-77 handle `paramPoly3` position but lines 129-142 leave its endpoint heading at the start heading. The affected helpers belong to `canonicalize_junction_connectors`; `TopologyRepair.run()` does not call that path, so this correction hardens an unwired utility and does not change the live map mutation path. |
| `topology/topology_validation.py` | BUGGY | Lines 48-80 use a line extrapolation for `poly3`, `spiral`, and `paramPoly3` endpoint pose in a connector validator. |
| `visualization/curvature_drift_plot.py` | BUGGY (reporting) | Lines 9-15 report curvature from arcs only. This plot is a human-facing domain-gap judgement artifact. |
| `visualization/heatmap_generator.py` | BUGGY (reporting) | Lines 55-82 explicitly render `spiral/poly3/default` as a line; Stage 6 emits this heatmap for quality review. |
| `visualization/lane_overlay.py` | BUGGY (reporting) | Lines 64-91 render all non-arcs as lines, making lane-quality previews geometrically false. |
| `visualization/map_diff.py` | BUGGY (reporting) | Lines 45-84 convert every non-arc plan-view geometry to a line. `run_full_domain_gap.py` uses this visual comparison. |
| `visualization/map_plotter.py` | BUGGY (reporting) | Lines 43-98 samples line, arc, and a local spiral only; `paramPoly3` returns no points. Pipeline stage previews therefore omit most map roads. |

The reporting fixes do not change any quality threshold or map XML. They ensure
that reviewers see the actual geometry represented by existing XODR records.
