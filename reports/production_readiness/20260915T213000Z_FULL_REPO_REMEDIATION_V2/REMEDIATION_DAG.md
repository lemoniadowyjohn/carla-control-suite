# Comprehensive Gap Audit — Remediation DAG

## AUDITED_SHA: 540b5c5f12b10ff1f1add6fa51cc2c5cabea2c2a

## Architecture

This audit produces dependency-ordered remediation packets of small scope. Each packet targets 1-3 related modules, starts with tests, implements minimum change, and has focused tests.

## Packet Dependency Chain

```
P0-A (CI truth) ──┬──> P0-B (large-map fail-closed)
                  ├──> P0-C (transactional staging)
                  ├──> P0-D (OSM-XODR matcher bugs)
                  └──> P0-G (geometry validator truth)

P0-D ──> P0-E (correspondence V2 data model)
P0-E ──> P0-F (correspondence V2 scoring)
P0-G ──> P0-H (inspection vs repair separation)
P0-G ──> P1-A (canonical geometry strictness)
P0-I ──> P0-J (DEM coverage)
P0-K ──> P0-L (stage dependency contract + reorder)

P1-A ──> P1-B (geometry numerical oracle)
P1-A ──> P1-C (road reference line service)
P1-C ──> P1-D (conservative bounds / projection)
P1-E ──> P1-F (lane offset)
P1-F ──> P1-G (lane generator provenance)
P1-G ──> P1-H (lane links)

P0-D ──> P1-I (OSM turn restrictions)
P0-E ──> P1-J (turn-lane functional model)
P1-K ──> P1-L (regulatory sign placement)
P1-L ──> P1-M (traffic-light source truth)
P1-M ──> P1-N (signal XML conformance)
P1-N ──> P1-O (XSD gate)

P1-P (roundabout safety) ──> P1-Q (connector reconstruction)
P1-Q ──> P1-R (literal topology)
P1-R ──> P1-S (component classification)
P1-T (building multipolygons) ──> P1-U (building foundation)
P1-V (source vs augmentation) ──> P1-W (pedestrian infrastructure)
P1-X (crosswalk hardening) ──> P1-Y (structure/elevation)
P1-Y ──> P1-Z (super-elevation audit)

P2-A (packaging) ──> P2-B (import origin guard)
P2-B ──> P2-C (artifact authority)
P2-C ──> P2-D (release branch plan)
P2-D ──> P2-E (warning codes)

RQ1 (determinism harness)
RQ2 (per-tile performance)
RQ4 (graph integrity regression)
RQ5 (split/leakage guards)
```

## Packet Inventory

### P0 (Critical — Must Complete First)

| Packet | Scope | Status |
|--------|-------|--------|
| P0-A | CI truth: integration candidates get CI, runtime health from actual command, no `if: always()` PASS | NEXT |
| P0-B | Large-map fail-closed: roundtrip False→FAIL, None→INCOMPLETE, exact tile-set check | NEXT |
| P0-C | Transactional large-map package: no hardlinks, SHA verification, atomic promotion | NEXT |
| P0-D | OSM-XODR matcher bugs: heading_error=0.0 truthiness, ambiguity margin inversion | NEXT |
| P0-E | Correspondence V2 data model: typed association, one-to-many support | AFTER P0-D |
| P0-F | Correspondence V2 scoring: incremental evidence terms, labeled fixtures | AFTER P0-E |
| P0-G | Geometry validator truth: prove/refute XML mutation bugs, wrong heading fallback | NEXT |
| P0-H | Inspection vs repair separation: mutation-free inspect, validate candidate | AFTER P0-G |
| P0-I | DEM CRS identity: separate bounds_native/crs_native/bounds_wgs84 | NEXT |
| P0-J | DEM coverage: replace diagonal ratio, strict fallback, no env override | AFTER P0-I |
| P0-K | Stage dependency contract: explicit capabilities, prerequisite enforcement | NEXT |
| P0-L | Stage reorder migration plan: gradual migration with frozen gates | AFTER P0-K |

### P1 (High Priority)

| Packet | Scope |
|--------|-------|
| P1-A | Canonical geometry strictness: exactly one primitive, reject unknown pRange |
| P1-B | Geometry numerical oracle: independent Fresnel for spiral |
| P1-C | Road reference line service: single abstraction owning pose_at_s, projection |
| P1-D | Conservative bounds/projection: analytic extrema, coarse-to-fine |
| P1-E | Lane width preservation: validate polynomial over full interval |
| P1-F | Lane offset: polynomial validation, structural freeze |
| P1-G | Lane generator provenance: orientation-aware directional inference |
| P1-H | Lane links: scope-correct validation, no -1→-1 fallback |
| P1-I | OSM turn restrictions: complete parser, routing tests |
| P1-J | Turn-lane functional model: lane-level movement intent |
| P1-K | Speed authority: explicit precedence function |
| P1-L | Regulatory sign placement: OSM coordinate → projection → s/t |
| P1-M | Traffic-light source truth: separate from augmentation |
| P1-N | Signal XML conformance: pinned schema, controller model |
| P1-O | XSD gate: OPENDRIVE_SCHEMA and CARLA_STATIC_COMPAT separate |
| P1-P | Roundabout safety: tests, documentation, V2 behind feature flag |
| P1-Q | Connector reconstruction: constrained primitive selection |
| P1-R | Literal topology: separate LITERAL_SPEC_GRAPH and RECOVERED_DIAGNOSTIC_GRAPH |
| P1-S | Component classification: explicit categories, UNKNOWN not auto-deleted |
| P1-T | Building multipolygons: preserve outer/inner rings |
| P1-U | Building foundation: ground/foundation z authority |
| P1-V | Source vs augmentation: provenance tagging |
| P1-W | Pedestrian infrastructure: separate support incrementally |
| P1-X | Crosswalk hardening: adversarial fixtures |
| P1-Y | Structure/elevation: canonical reference-line service |
| P1-Z | Super-elevation audit: fidelity report, no synthesis |

### P2 (Medium Priority)

| Packet | Scope |
|--------|-------|
| P2-A | Packaging: define extras, clean-venv testing |
| P2-B | Import origin guard: CI proves modules from checkout |
| P2-C | Artifact authority: all docs/registry refer to same hash |
| P2-D | Release branch plan: integration→stabilization→candidate→protected |
| P2-E | Warning codes: stable IDs, severity, release impact |

### Research Infrastructure

| Packet | Scope |
|--------|-------|
| RQ1 | Determinism harness: four-level, all evidence fields |
| RQ2 | Per-tile performance: profile, optimize, parity tests |
| RQ4 | Graph integrity regression: permanent self-loop tests |
| RQ5 | Split/leakage guards: dataset-manifest validators |

## Recommended First Packet

**P0-A (CI Truth)** is the highest-priority first packet because:
1. It enables verification of all other packets via CI
2. It fixes `if: always()` hard-coded PASS in carla-runtime.yml
3. It ensures integration candidates get CI on their exact SHA
4. It requires only CI/status changes (no production code mutation)
5. It is fully testable offline

## Global Quality Rules

For every packet:
1. Inspect current HEAD
2. Write failing regression test
3. Implement minimum change
4. Focused test
5. Full related subsystem tests
6. Commit

Every 5-8 packets: full pytest, wheel build, pip check, governance, RQ contract, provenance.

## Stop Conditions

Stop a packet when: source authority ambiguous, same file owned by another agent, fix requires map-of-record mutation, Unreal, live CARLA, external real dataset, algorithmic requirement lacks evidence.

## Never Do

Never force push, rewrite history, modify submission, change RQ wording, promote map-of-record, start CARLA, start UE, claim runtime certification, claim RQ3/RQ5, silently weaken thresholds, mark NOT_RUN as PASS.
