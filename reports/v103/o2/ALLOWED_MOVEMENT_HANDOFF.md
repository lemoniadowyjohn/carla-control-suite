# V103-O2 — Handoff contract: `AllowedMovementReport`

**Owner:** OpenCode · **Date:** 2026-11-13 · **Status:** source ready, not gate-integrated
**Schema:** `reports/v103/o2/ALLOWED_MOVEMENT_SCHEMA.json` (`osm_allowed_movement/v1`)
**Modules (NEW, no existing file was edited):**
`ultimate_pipeline/enrichment/osm_restrictions.py`,
`ultimate_pipeline/enrichment/osm_legal_movement.py`

This is the handoff for **Codex C1 / C2** (release acceptance and terminal
authority). OpenCode built the source layer and the comparison API; it did
**not** integrate a gate, did **not** rewrite any OpenDRIVE, and did **not**
touch a release-authority file.

---

## 1. What this is

A **source-grounded legal movement graph** built from OSM facts, joined to
the XODR **only** through O1's verified oriented source correspondence.

The property it exists to protect:

> **A missing relation does not mean every movement is legal.**

Three things are kept distinct and are never collapsed:

| | verdict | `rule_source` |
|---|---|---|
| explicit denial | `DENY_SOURCE_PROVEN` | `osm_no_restriction`, `osm_oneway`, `osm_access`, `osm_only_restriction` |
| known default permission | `ALLOW_SOURCE_PROVEN` | `osm_default_permission`, `osm_only_restriction` |
| no source evidence | `UNKNOWN_NO_SOURCE` | `osm_no_source_evidence` |

Three further verdicts cover the cases where the question cannot be
answered from the source at all: `AMBIGUOUS_MAPPING`,
`UNSUPPORTED_CONDITIONAL`, `PHYSICAL_DISCONTINUITY`.

**Topology existence is not legal eligibility.** A shared node proves two
ways are *connected*; it says nothing about whether the movement is legal
for the actor. Those are separate computations.

---

## 2. The API

```python
from ultimate_pipeline.enrichment.osm_restrictions import (
    read_osm_document, parse_restrictions, resolve_access, resolve_oneway,
)
from ultimate_pipeline.enrichment.osm_legal_movement import (
    build_movement_graph, build_allowed_movement_report,
    compare_with_junction_connections, render_report,
    MovementStatus, SCHEMA_VERSION,
)

document = read_osm_document(path)          # raises OsmSourceError -> BLOCKED_INPUT
graph    = build_movement_graph(document, vehicle_class="motor_vehicle")
report   = build_allowed_movement_report(graph, default_permission=True)

payload  = report.to_dict()                 # validates against the schema
text     = render_report(report)            # canonical JSON
```

### `AllowedMovementReport`

| field | meaning |
|---|---|
| `schema_version` | `osm_allowed_movement/v1` |
| `status` | `PASS` / `INCOMPLETE` / `BLOCKED_INPUT` / `NOT_RUN`. **`PASS` means the measurement completed — not that the map is release-eligible.** |
| `reason` | empty on PASS; otherwise why the report is not a completed measurement |
| `vehicle_class` | the actor every verdict is for |
| `source` | `sha256`, `bytes`, `complete` |
| `counts` | movements per verdict |
| `restrictions` | `parsed` / `applied` / `contradicted` / `missing` / `ambiguous` / `undecidable` |
| `movements` | one record per candidate movement |
| `notes` | the interpretation switches in force |

### `MovementRecord`

`from_way`, `to_way`, `via_nodes`, `via_ways`, `vehicle_class`, `status`,
`rule_source`, `evidence`, `reason`.

`evidence` carries precise ids: `way:<id>`, `node:<id>`, `relation:<id>`.

---

## 3. The interpretation switch — read this before gating on it

`build_allowed_movement_report(graph, default_permission=True|False)` decides
what an **ungoverned** movement between two decidable ways means.

* `True` → `ALLOW_SOURCE_PROVEN` with `rule_source = "osm_default_permission"`.
  This is the OSM data model's default: a movement at a shared node is
  permitted unless a restriction forbids it.
* `False` → `UNKNOWN_NO_SOURCE`.

**The switch is recorded in `notes[0]`** so a reader can always see which
reading produced the verdicts.

**This is a policy decision, not a fact.** The default permission is a
property of the OSM *data model*; it is **not** evidence that a particular
map permits a particular movement. A gate that wants to assert "this map
permits this movement" should use `default_permission=False` and treat
`UNKNOWN_NO_SOURCE` as not-proven.

---

## 4. The enforcement boundary (dispatch item 5)

The module **defines the boundary but does not enforce it**. It says what
the source permits, denies and leaves undecided. It does not:

* rewrite a generated `laneLink`;
* change an OpenDRIVE junction;
* claim that CARLA's runtime routing honours the verdict.

Two distinct enforcement surfaces exist, and they must not be conflated:

1. **A validation gate.** A generated junction connection whose OSM
   movement is `DENY_SOURCE_PROVEN` is a *finding*: the generated link
   asserts a movement the source forbids. This is checkable offline and is
   the surface a release gate should use.
2. **A route planner.** A planner that must not route through a denied
   movement needs runtime enforcement. That is a CARLA-side concern and is
   **not** implemented here; the report explicitly carries
   `runtime_certification: NOT_RUN` semantics by never claiming enforcement.

`compare_with_junction_connections()` produces the input for surface (1):
one `ConnectionComparison` per generated junction connection, bound to its
OSM movement **only** where the O1 correspondence is EXACT/HIGH and
oriented. Where the binding is missing, the comparison is
`UNKNOWN_NO_SOURCE` with the reason stated — it is never guessed.

---

## 5. What is NOT modelled (stated, not hidden)

* **Conditional restrictions** need a clock/vehicle context.  Without one
  they are `UNSUPPORTED_CONDITIONAL` and the affected movements are
  `UNSUPPORTED_CONDITIONAL` — never silently ignored and never silently
  permitted.  The pinned real OSM carries **4** `oneway:conditional` ways
  and **0** conditional turn restrictions.
  **A context IS now supported** (see §9): `RestrictionContext(clock=...,
  day=...)` evaluates the daily-window subset
  (`no @ (10:00-16:00)`, `yes @ (Mo-Fr 07:00-09:00)`).  A dated range or
  any other form stays `None` — undecidable, never guessed.
* **`no_entry` / `no_exit`** are valid OSM but need a from/to semantics
  this module does not model; they are reported `UNSUPPORTED_FORM`, not
  dropped.
* **A `restriction` tag on a WAY** (rather than on a relation) defines
  nothing.  The pinned real OSM carries exactly **one** such tag; it is
  reported `INCOMPLETE` with the reason, and it is counted in
  `restrictions.ambiguous`.
* **`turn:lanes` is NOT used to decide legality.** It indicates allowed /
  intended lane turn *directions*; the final lane-to-lane mapping needs
  directed endpoints, actual lanes and junction connector geometry. This
  module deliberately does not infer lane-level connections.
* **Lane-level enforcement is not implemented** and is out of scope by
  design (see §4).

---

## 6. What the source actually contains (measured, not assumed)

The pinned Ingolstadt OSM (`b9e07465…`, 11,154,738 B, 74,874 nodes,
17,250 ways, 9 relations):

| fact | value |
|---|---|
| **restriction relations** | **0** |
| relations of any type | 9, all `multipolygon` |
| `oneway` tags | 2,216 ways |
| `oneway:conditional` | 4 ways |
| `access` | 2,016 ways |
| `vehicle` | 134 ways |
| `motor_vehicle` | 324 ways |
| `psv` / `bus` | 2,777 / 1,283 ways |
| `bicycle` / `hgv` | 2,308 / 44 ways |
| `junction=roundabout` | 148 ways |
| `turn:lanes` | 333 ways |
| `restriction` on a **way** | 1 (malformed form) |

**Consequence, stated plainly: the pinned source contains no turn
restriction at all.** So on the real map no movement can be
`DENY_SOURCE_PROVEN` by a turn restriction; every turn-level question
falls back to the default permission. The denials that do exist come from
`oneway` and `access`.

Measured on the real map, `motor_vehicle`, `default_permission=True`:

| verdict | movements |
|---|---|
| `ALLOW_SOURCE_PROVEN` (default permission) | 47,346 |
| `DENY_SOURCE_PROVEN` (oneway / access) | 15,616 |
| `PHYSICAL_DISCONTINUITY` (grade separated) | 1,866 |
| `UNSUPPORTED_CONDITIONAL` | 32 |
| `UNKNOWN_NO_SOURCE` | 0 |

---

## 7. How to integrate it (for the gate owner)

```python
report = build_allowed_movement_report(graph, default_permission=False)
if report.status != "PASS":
    ...  # BLOCKED_INPUT -- do not proceed
for comparison in compare_with_junction_connections(root, graph, associations):
    if comparison.status == "DENY_SOURCE_PROVEN":
        ...  # a generated link asserts a movement the source forbids
```

Two rules for the gate owner:

1. **Never read `ALLOW_SOURCE_PROVEN` as "release-eligible".** It is
   "the source permits this", and with `rule_source =
   "osm_default_permission"` it is the data model's default, not a fact
   about the map.
2. **Never let `UNKNOWN_NO_SOURCE` pass as a permission.** It means the
   source says nothing, which is different from saying yes.

---

## 8. Verification

* `tests/unit/test_v103_o2_legal_movement.py` — **32 tests**, all passing.
  Synthetic fixtures cover the dispatch's adversarial list: T-junction with
  `no_left_turn`, `only_straight_on`, via-way restriction, reverse oneway,
  roundabout, U-turn form, grade-separated crossing, bus exemption,
  bicycle contraflow, conditional restriction (with and without a clock
  context), conflicting tags, a malformed restriction, a missing member,
  and an ambiguous XODR correspondence.
* `tests/unit/test_v106_o2_gap_closure.py` — **9 tests** for the three
  gap-closure fixes.
* **9 mutation controls, 9 detected, 0 missed.**  The first pass detected
  only 4 of the first 4 and **missed** the via-way control; re-examining
  it showed the control was not meaningful (both code paths carry
  `via_ways`), so it was reformulated to target the defect that actually
  matters — that a via-way which does not connect must forbid nothing.
  A second control was missed because the weekday mutation did not change
  the outcome for `"Mo"`; the test was strengthened with a mid-week day.
* The CLI verifies the OSM SHA-256 against the pinned manifest, refuses a
  Git-LFS pointer, admits the source through a bounded entity-free scan,
  and exits non-zero on any missing or stale input.
* O1 + O2 related suites: **148 passed**.

---

## 9. Open items for the next iteration

1. ~~**Via-WAY chains** do not yet split a candidate movement.~~ **CLOSED.**
   A via-way restriction is now evaluated as its own movement class: the
   via-way must actually connect the from-way and the to-way, and the
   record carries the entry and exit nodes.  A via-way that does not
   connect forbids nothing and is reported `UNKNOWN_NO_SOURCE` with the
   reason `the via-way does not connect the from-way and the to-way`.
2. ~~**The U-turn form** is parsed but the `no_u_turn` semantics (from ==
   to through a node) are not yet distinguished from an ordinary turn.~~
   **CLOSED.** A `no_u_turn` forbids the **self-movement**, which the
   node-based candidate set never contains; without the explicit handling
   a parsed `no_u_turn` was reported as applied while changing nothing.
3. ~~**Conditional restrictions** need a clock/vehicle context parameter.~~
   **CLOSED.** `RestrictionContext(clock="HH:MM", day="Mo")` is accepted by
   `parse_restrictions(context=...)` and by
   `build_movement_graph(restriction_context=...)`.  The daily-window
   subset is evaluated; a dated range stays undecidable.  A conditional
   that does **not** hold at the supplied moment is still RECORDED (as
   `INCOMPLETE` with the reason), not silently dropped.
4. **No gate integration.** The comparison API is the input; whether a
   denied movement blocks a release is the gate owner's decision, and the
   **enforcement boundary is not implemented**.
5. **The report does not cover lane-level connections**, by design: the
   dispatch states that `turn:lanes` alone does not specify lane-to-lane
   connections.

### The API after the gap closure

```python
from ultimate_pipeline.enrichment.osm_restrictions import RestrictionContext

graph = build_movement_graph(
    document,
    vehicle_class="motor_vehicle",
    restriction_context=RestrictionContext(clock="12:00", day="Mo"),
)
report = build_allowed_movement_report(graph, default_permission=False)
```

With a context, a conditional restriction that holds becomes an ordinary
`DENY_SOURCE_PROVEN`; one that does not hold is recorded as not applying.
Without a context it stays `UNSUPPORTED_CONDITIONAL`.
