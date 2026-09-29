# Independent verification: O1–O19 release-provenance work (branch `o20-failure-recovery-resume-audit`)

Scope: this is a **verification pass**, not new pipeline work. It independently
re-derives / disproves the claims in commits `f7934c13` (O1), `f8e900c2` (O2),
`2f67676e` (O4), `4972b685` (O12), `7dca6dd1` (O13), `6f9da5a9` (O19), and
performs the required SHA-binding cross-check. No map promotion, no evidence
mutated, no tests weakened.

## Ground truth: current authoritative SHA

Independently re-derived (not trusted from any report), two ways:

```
ultimate_pipeline.carla_tools.map_registry.verify_pinned_map('auto_map_of_record')
  -> sha256_actual = 370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8
  -> bytes_actual  = 149799632
  -> path           = campaigns/ingolstadt_cooked_perception_v1/candidate/
                       ingolstadt_perception_map_of_record_20260916_232831.xodr
  -> verification_status = VERIFIED
```

```python
import hashlib
h = hashlib.sha256()
# streamed the actual file on disk, independent of map_registry.py's own hashing code
h.hexdigest() == "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8"  # True
```

Both agree. This SHA (`370abbbb...`) is the reference used for every SHA-binding
check below.

---

## O1 (`f7934c13`) — "enforce current-pin cook provenance chain"

**Verdict: substantiated.** Read the real diffs (not just the commit message) for
`ultimate_pipeline/tiling/large_map_package.py`, `scripts/cook_full_grid_tiles.py`,
`tools/stage_large_map_import_package.py`, `ultimate_pipeline/tiling/tile_fbx_generator.py`.

- `cook_full_grid_tiles.py` genuinely calls `verify_pinned_map("auto_map_of_record")`
  **at function-execution time** inside `cook_all_tiles()` (not only at import time,
  where `PINNED_XODR = Path(_pinned["path"])` is also set) — re-hashes the file after
  the fresh lookup and fails closed on any byte-size or SHA drift between lookup and
  hashing.
- FBX reuse (`reuse_candidate`) is genuinely gated on
  `manifest.source_provenance.map_of_record_sha256 == current xodr_sha`, plus a
  second hash check of the on-disk FBX against the manifest's own recorded FBX hash
  — matches claim #3.
- `large_map_package.py::stage_large_map_package` genuinely rejects mixed-generation
  tile sets (distinct source SHAs among staged tiles) and missing-manifest tiles when
  in "strict provenance" mode, cleaning up partially-staged output on failure —
  matches claims #4, #6, #7.
- Tile ordering is by `(tx, ty)` parsed from filename, never by `mtime` — matches
  claims #2, #8.
- Ran the tests myself: `tests/unit/test_o1_cook_provenance_chain.py` — **16/16
  passed**. Also ran the pre-existing `tests/unit/test_large_map_package.py` — 32/32
  passed (no regression from O1's changes).

No fail-open pattern found in O1 itself.

---

## O2 (`f8e900c2`) — "large-map package contract audit + mechanical checks"

**Verdict: the checks are real and mechanical (they inspect real package
contents, not just assert prose) — but they are effectively decorative, because
O4's aggregator silently discards their FAIL status. See the O4 section below for
the reproduced bug.**

`audit_large_map_package_contract()` genuinely globs the package directory
(`*.xodr`, `*_Tile_*.xodr`, `*_Tile_*.fbx`), parses tile filenames, checks
descriptor fields, checks for duplicate `(tx, ty)` indices, and checks tile
manifests for header-offset agreement. This is real code inspecting real
filesystem state, not a hardcoded "PASS" (unlike O13 — see below). Ran
`tests/unit/test_o2_large_map_package_contract.py` — **8/8 passed**.

The problem is not that O2's checks are fake — it's that nothing actually
*consumes* their FAIL status in a way that blocks anything (found while
verifying O4; documented there).

---

## O4 (`2f67676e`) — "deterministic import package preflight CLI"

**Verdict: the CLI runs and most of its 14 checks work as claimed — but found
and reproduced a real fail-open bug in the aggregation logic.**

Ran the CLI myself against real and synthetic packages; also ran
`tests/unit/test_o4_preflight_import_package.py` — **8/8 passed** (matches the
commit's claimed coverage: missing tile, stale tile, mismatched XODR, malformed
package, wrong tile naming, missing frame metadata, 2 READY cases). Note that
none of the 8 tests cover a scenario where `audit_contract` (O2's check) is the
*only* failing check — that's precisely the gap below, and it slipped through
because it was never tested.

### Real bug found: `audit_contract` FAIL never blocks the overall verdict

`tools/preflight_import_package.py::preflight_package()` appends the O2 contract
audit result directly:

```python
audit = audit_large_map_package_contract(str(pkg_dir), expected_tile_size_m=expected_tile_size_m)
checks.append({"check": "audit_contract", "status": audit.status, ...})   # status ∈ {"PASS","FAIL"}
...
has_blocked = any(c.get("status") == "BLOCKED" for c in hard_checks)      # never matches "FAIL"
has_incomplete = any(c.get("status") == "INCOMPLETE" for c in hard_checks)
overall = "BLOCKED" if has_blocked else ("INCOMPLETE" if has_incomplete else "READY")
```

`audit_large_map_package_contract()` (O2) only ever returns `status ∈ {"PASS",
"FAIL"}` — it never returns `"BLOCKED"`. The aggregator only tests for
`"BLOCKED"` / `"INCOMPLETE"`. A `"FAIL"` from the contract audit therefore
**falls through both branches and is silently ignored** by the overall verdict.

**Reproduced end-to-end via the actual CLI** (script committed at
`reports/verification/repro_preflight_failopen.py`, run it yourself:
`python reports/verification/repro_preflight_failopen.py`):

```
$ python tools/preflight_import_package.py --package-dir <pkg> \
    --expected-xodr-sha <sha matching the synthetic package> --min-free-gib 0.001
Preflight: READY (READY_FOR_IMPORT)
Checks: 9 PASS / 0 BLOCKED / 4 INCOMPLETE (total 14)
  [PASS] authoritative_xodr
  [PASS] validate_staged_package
  [FAIL] audit_contract: ["expected exactly one .xodr in package dir, found 2:
         ['Ingolstadt.xodr', 'Ingolstadt_Tile_0_0.xodr']"]
  ...
Exit code: 0
```

The synthetic package deliberately violates exactly the invariant O2's audit
was built to catch (per-tile XODR leak → duplicated road authority risk,
invariant #1/#7 in O2's own commit message). `[FAIL] audit_contract` is
printed in the human-readable output and present in the JSON, but the tool
still reports `READY (READY_FOR_IMPORT)` and exits `0`. Anything downstream
that gates on the exit code or the `status`/`claim` field (rather than
manually scanning every individual check row) would proceed.

This is precisely the "unenforced-in-name-only" pattern the task asked me to
hunt for: the check is real, its output is real, but it is not wired into the
thing that actually decides pass/fail.

---

## O12 (`4972b685`) vs Phase10 (`reports/production_readiness/20260924T130000Z_PHASE10_STATIC_RELEASE_MATRIX/`)

**They do NOT agree, and picking one as authoritative would be wrong — they are
answering different questions, and O12's own tool has real defects that make
several of its non-PASS rows misleading rather than genuinely "stale."**

**What each artifact actually is:**
- **Phase10** is the raw output of *actually running*
  `measure_candidate_acceptance.run_gates()` against the current pinned XODR
  (verified: `measure_candidate_acceptance/map_acceptance.json` has
  `final_xodr_sha256 == 370abbbb...`, `valid_for_experiments: true`,
  `hard_fail_reasons: []`). It is a **gate-execution report**.
- **O12** (`tools/current_map_static_release_matrix.py`) does not run any gates.
  It scans a hardcoded list of 14 *pre-existing* evidence files and checks
  whether each one's embedded SHA matches the current pin. It is a
  **staleness/binding audit of past evidence**, not a re-execution of the gates.

These are legitimately different kinds of artifact, so a flat "agree/disagree"
is itself an oversimplification the task warned against — but there is a
precise, reproducible discrepancy worth flagging:

### Finding 1 — O12's `map_acceptance` gate can never see Phase10's evidence, by construction

O12's own code (`tools/current_map_static_release_matrix.py:93`):
```python
_record("map_acceptance", "python scripts/measure_candidate_acceptance.py <xodr>", None)
```
`evidence=None` is **hardcoded** for this row (and 5 others: `lane_topology`,
`road_links`, `junction_links`, `artifact_fingerprint`, `waivers`). No evidence
path is ever looked up for these rows, so they can only ever report `NOT_RUN`
— regardless of what evidence exists in the repo, and regardless of when the
tool is (re-)run.

I re-ran `build_matrix()` myself, right now, with Phase10's report already on
disk:
```
map_acceptance      -> NOT_RUN   evidence_path= None
artifact_fingerprint -> NOT_RUN  evidence_path= None
lane_topology        -> NOT_RUN  evidence_path= None
road_links           -> NOT_RUN  evidence_path= None
junction_links        -> NOT_RUN evidence_path= None
waivers              -> NOT_RUN  evidence_path= None
```
Despite Phase10's `measure_candidate_acceptance/map_acceptance.json` being
real, current-pin-bound (`370abbbb...`), zero-hard-failure evidence for
**exactly** the command O12 names for this row
(`python scripts/measure_candidate_acceptance.py <xodr>`), O12 structurally
cannot discover it. This is not a timing artifact (Phase10 postdates O12 by
~1h; O12 was never re-run) — it's a code-level gap: even after Phase10 existed,
re-running O12 still reports `NOT_RUN`.

### Finding 2 — O12's SHA-binding extractor misses real current-pin evidence it does look at (false STALE_OR_UNBOUND)

For the 8 rows that *do* have a hardcoded `evidence_path`, O12's `_record()`
only checks a fixed, shallow set of field names
(`map_sha256`, `input_xodr_sha256`, `xodr_sha256`, `map_of_record_sha256`,
`auto_xodr_sha256`, or nested `.sha256` under those, or
`source_provenance.map_of_record_sha256`).

At least two of the evidence files it names carry the exact current-pin SHA
under a field shape the extractor doesn't check:

- `reports/production_readiness/20260921_XODR_VALIDATOR_CONVERGENCE/04_VALIDATOR_DISAGREEMENTS.json`
  (cited for `xml_validity`, `planview_completeness`, `geometry_validation`,
  `crs_checks`) contains `pinned_maps.auto.map_sha256 == "370abbbb..."` with
  `envelope_status: "PASS"`, `n_errors: 0`, `sub_statuses.XML_BASIC_INTEGRITY:
  "PASS"`, `sub_statuses.CARLA_STATIC_COMPAT: "PASS"` — i.e. this file
  genuinely is current-pin-bound, passing evidence for exactly these gates.
  O12 reports all four as `STALE_OR_UNBOUND` / `source_map_sha256: null`
  because it never looks under `pinned_maps.auto.map_sha256`.
- `reports/production_readiness/20260919T000000Z_PRODUCTION_CLOSURE/00_BASELINE.json`
  (cited for `component_reachability`) contains
  `map_of_record.sha256 == "370abbbb..."` with `verified_this_run: true` — also
  genuinely current-pin-bound. O12 reports `STALE_OR_UNBOUND` because
  `"map_of_record"` (a nested dict) is not in its flat field list (only the
  flat string key `"map_of_record_sha256"` is checked).

Reproduced directly: calling `_record('xml_validity', ..., '.../04_VALIDATOR_DISAGREEMENTS.json')`
returns `source_map_sha256: null, status: "STALE_OR_UNBOUND"` even though the
file plainly contains the matching SHA two keys deep.

### What is genuinely stale/unbound (not an extractor artifact)

- `lane_count_classification` gate: its evidence
  (`.../20260918T000000Z_PRODUCTION_CLOSURE/lane_count_classification.json`)
  has `input.sha256` literally set to a **file path string**, not a hash
  (`"sha256": "campaigns/.../ingolstadt_perception_map_of_record_20260916_232831.xodr"`).
  This is a genuine defect in that upstream report (wrong field content), and
  O12 correctly reports it as unbound — though for a different reason than
  "no SHA found": the SHA field exists but is corrupted, which O12's error
  message doesn't distinguish from "absent."
- `gap026` gate: `MASTER_GAP_REGISTER.json` only mentions the current pin's SHA
  as a truncated prefix inside free-text prose ("...370abbbb...,
  currently valid_for_experiments=true..."), not in a structured field. O12
  correctly declines to bind on this (prose isn't a safe binding source) —
  this is a reasonable conservative call, not a bug.

### Bottom line for O12 vs Phase10

Of O12's 14 rows, only **1** (`tile_readiness`) is a genuine, correctly-detected
PASS bound to the current pin (verified: `COOK_RESULTS.json`'s
`source_provenance.map_of_record_sha256 == 370abbbb...`). Of the remaining 13:
- 6 are structurally incapable of ever showing anything but `NOT_RUN`
  (hardcoded `evidence=None`), including `map_acceptance` — the exact gate
  Phase10 actually ran and passed for the current pin.
- At least 2 more (`xml_validity`/`planview_completeness`/`geometry_validation`/
  `crs_checks` share one evidence file, `component_reachability`) are reported
  `STALE_OR_UNBOUND` due to a narrow field-matching heuristic, when the cited
  evidence file actually does carry the current pin's SHA with a PASS result.
- 2 are genuinely stale/unresolvable for the reasons above (corrupted field,
  prose-only mention).

O12's headline (`overall_static_evidence_status: STALE_OR_UNBOUND`) is
therefore **not a reliable signal that the underlying gates actually failed or
are stale for the current map** — Phase10 shows several of them demonstrably
passed for the current pin. It is a signal that O12's own extraction logic has
real gaps. Neither report should be treated as the authoritative release
verdict as-is; O12 needs its evidence-field extraction widened (at minimum:
`pinned_maps.<role>.map_sha256`, `map_of_record.sha256`) and its six
hardcoded-`None` rows wired to real evidence paths (Phase10's directory is the
obvious source for `map_acceptance` at minimum) before its `STALE_OR_UNBOUND`
verdict can be trusted.

---

## O13 (`7dca6dd1`) — "configuration authority audit"

**Verdict: this is documentation encoded as JSON, not a mechanical audit.**
Unlike O2 (which really globs/parses package contents), `build_audit()` in
`tools/configuration_authority_audit.py` returns a **hand-authored, static
Python list** of 11 rows (`setting`, `category`, `authority`, `duplicates`,
`resolution` — all literal strings written by the commit's author). Nothing in
the function inspects the actual source files it makes claims about (e.g. the
claim that `cook_full_grid_tiles.py` "re-resolves verify_pinned_map at
runtime" is asserted as prose here, not re-verified by this tool — though I
independently confirmed it's true by reading the O1 diff above). `status:
"PASS"` is a **hardcoded literal** in the return dict — there is no code path
that could ever produce `"FAIL"`.

The 3 unit tests (`tests/unit/test_o13_configuration_authority_audit.py`, all
3 pass) only assert that the hardcoded dict contains certain hardcoded
strings — they test that the documentation says what it says, not that the
documentation is true of the code.

This is a real finding worth flagging on its own terms: O13 is legitimately
useful as a human-readable catalogue of known config-authority duplication
(and its individual claims about D-category "duplicated production authority"
settings do check out against what I read in O1/map_registry.py), but it must
not be treated as a verified/enforced audit gate — it cannot fail, by
construction.

---

## O19 (`6f9da5a9`) — "final release receipt schema validator"

**Verdict: confirmed — no real release receipt document exists anywhere in the
repo. The validator has nothing real to validate against.**

Searched the full repository for anything matching this schema (section names
`repository, source, map, visual_package, unreal_carla, testing, runtime,
research, known_gaps`, and for any file named like a release receipt):

```
grep -r '"unreal_carla"\|"visual_package"\|final_release_receipt' .
  -> only tools/final_release_receipt.py and tests/unit/test_o19_final_release_receipt.py

find . -iname '*release_receipt*' -o -iname '*RELEASE_RECEIPT*'
  -> only tools/final_release_receipt.py, tests/unit/test_o19_final_release_receipt.py
     (+ their compiled .pyc caches)
```

No `FINAL_RELEASE_RECEIPT.json` (or any document under any name) exists. The
O19 commit itself only added the validator tool and its unit test — it never
ran the validator against a real receipt or committed one. The validator's own
logic is sound as far as it goes (rejects unknown status values, requires all
9 top-level sections present, explicitly does not treat "missing evidence" as
implicit PASS — verified via its own 4 unit tests, 4/4 pass, including
`test_absent_evidence_cannot_serialize_as_pass`), but **this commit should be
recorded as NOT_RUN against real release evidence, not as a PASS on anything
real.** No release receipt has been produced by O1–O20 or any prior work in
this repo as of this verification.

---

## Fail-open / unenforced-in-name-only patterns found (summary)

1. **O4 aggregation bug (real, reproduced):** `audit_large_map_package_contract`
   (O2) returns `"FAIL"`, but `preflight_import_package.py`'s aggregator only
   checks for `"BLOCKED"`/`"INCOMPLETE"` — a contract-audit FAIL is silently
   dropped from the overall verdict. CLI can report `READY (READY_FOR_IMPORT)`,
   exit code `0`, on a package with a real structural violation (verified:
   per-tile XODR leak). Repro script committed at
   `reports/verification/repro_preflight_failopen.py`.
2. **O12 six-row dead-evidence gap (real):** `map_acceptance`,
   `artifact_fingerprint`, `lane_topology`, `road_links`, `junction_links`,
   `waivers` are wired with `evidence=None` and can never report anything but
   `NOT_RUN`, even when real bound evidence exists (Phase10, for
   `map_acceptance` specifically).
3. **O12 false-stale rows (real):** narrow field-name matching causes at least
   5 of O12's rows to report `STALE_OR_UNBOUND` on evidence files that actually
   do carry the current pin's SHA with a PASS verdict.
4. **O13 is unconditional-PASS documentation, not an audit gate:** cannot ever
   fail by construction; its individual claims are plausible (and the ones I
   spot-checked against O1's real diff held up) but are asserted, not verified,
   by the tool itself.
5. **O19 has nothing to validate:** the schema validator is sound in isolation,
   but zero real release receipts exist in the repo, so its "PASS" test
   results are about the validator's own unit tests, not about any actual
   release.

## What held up (no issue found)

- O1's provenance-chain enforcement in `cook_full_grid_tiles.py` and
  `large_map_package.py` is real, executes `verify_pinned_map()` at
  execution time (not just import time), fails closed on mixed
  generations/missing provenance/stale FBX, and its 16 new tests + the 32
  pre-existing `test_large_map_package` tests all pass.
- O2's `audit_large_map_package_contract()` genuinely inspects real package
  contents (not hardcoded); its 8 tests pass; it correctly flagged the
  synthetic per-tile-XODR-leak package I built as FAIL. The bug is downstream
  (O4), not in O2 itself.
- The current pinned map SHA (`370abbbb...`) is independently confirmed via
  two separate methods and is the SHA actually embedded in Phase10's
  `map_acceptance.json`, `00_BASELINE.json`, `04_VALIDATOR_DISAGREEMENTS.json`,
  and `COOK_RESULTS.json` — the underlying evidence chain for the current map
  is real, it is specifically O12's *matrix tool* that fails to see most of
  it correctly.
