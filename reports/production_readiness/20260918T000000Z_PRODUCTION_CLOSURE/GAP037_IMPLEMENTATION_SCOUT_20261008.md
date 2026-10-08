# GAP-037 Implementation Scout — Read-Only Scope Report

**Date**: 2026-10-08
**Task**: Scoping only for GAP-037 (waiver model has a single boolean `waivable` flag per gate with no
taxonomy of NON-waivable categories).
**Agent role**: READ-ONLY. No code was implemented. No gap register, no pending-policy file, no
config was edited. This report file is the only artifact written (plus a throwaway name-diff script
in `%TEMP%`, outside the repo).
**No policy recommendation is made and no option is selected.** Step 5 presents interaction facts only.

**Baseline**: branch tip `f6af647a`. Working tree has 10 modified tracked files (unrelated to this
scout); I touched none of them.

---

## Headline finding (read Step 1 before planning anything)

**The taxonomy GAP-037 asks for already exists in this repo, is committed, is an ancestor of HEAD,
and its test suite is green.** `ultimate_pipeline/contracts/stage_contracts.py:154-326` defines a
5-value `GateClass` enum, a `NON_WAIVABLE_CLASSES` frozenset, a 24-entry `GATE_CLASS_REGISTRY`, a
`classify_gate` resolver, and `production_gate_waiver_allowed` which fails closed on unknown and
non-waivable classes. `ultimate_pipeline/tests/unit/test_waiver_taxonomy.py` (150 lines, 14 tests)
locks this behaviour and **passes** — I ran it:

```
python -m pytest ultimate_pipeline/tests/unit/test_waiver_taxonomy.py -q
14 passed in 1.89s
```

Provenance: commit `627afe9f fix(governance): make integrity gates structurally non-waivable
(NEW-210/GAP-037)`; `git merge-base --is-ancestor 627afe9f HEAD` → **ANCESTOR**.

So the register entry `MASTER_GAP_REGISTER.json:677` ("needs a human policy decision on whether to
add a gate-class taxonomy to the waiver model") and `GAP037_POLICY_PROPOSAL.md` predate this commit
and no longer describe the code. **The residual GAP-037 gap is not "no taxonomy" — it is (a) taxonomy
coverage vs. the 10 named categories and (b) whether the taxonomy is actually *wired to anything*.**
Both are quantified below. I am not making a policy call on which framing is correct.

---

## Step 1 — Where the waiver logic actually lives

### 1.1 The taxonomy itself (already present)

`ultimate_pipeline/contracts/stage_contracts.py`:

| Line | What |
| --- | --- |
| `:46-67` | `QualityStatus` StrEnum: `PASS/FAIL/INCOMPLETE/NOT_RUN/BLOCKED_EXTERNAL/WAIVED`. `WAIVED` docstring (`:57-59`) states WAIVED is **never** PASS. |
| `:158-165` | `GateClass` StrEnum, 5 values: `IDENTITY_INTEGRITY`, `STRUCTURAL_INTEGRITY`, `QUALITY_DEVIATION`, `HEURISTIC_ADVISORY`, `RUNTIME_DEPENDENT`. |
| `:168-174` | `NON_WAIVABLE_CLASSES = frozenset({IDENTITY_INTEGRITY, STRUCTURAL_INTEGRITY, RUNTIME_DEPENDENT})` |
| `:179-208` | `GATE_CLASS_REGISTRY`, 24 string keys → classes. |
| `:211-219` | `classify_gate(name)` — registry lookup, returns `None` on unknown. Docstring `:214-216`: "Unknown gate classes fail closed: callers must treat None as non-waivable, never default to QUALITY_DEVIATION." |
| `:222-230` | `_coerce_gate_class` |
| `:233-262` | `_worst_of` severity reducer: `FAIL(5) > INCOMPLETE(4) > BLOCKED_EXTERNAL(3) > WAIVED(2) > NOT_RUN(1) > PASS(0)`; unknown → INCOMPLETE. |
| `:265-298` | `governed_waiver_allowed(waivers, child, gate_class=None)` — **generic** utility. Taxonomy only applies when `gate_class` is *explicitly passed* (`:291-294`); otherwise it preserves the legacy "any exact-name non-blank justification waives" semantics. |
| `:301-326` | `production_gate_waiver_allowed(waivers, child)` — **the strict production check**. `:318-322`: unknown name → False; non-waivable class → False regardless of justification; otherwise requires exact-name non-blank text. |
| `:352-517` | `promote_aggregate_detailed(...)`. `:449-462` is the decision point: `if enforce_taxonomy:` use `production_gate_waiver_allowed`, else use the generic `governed_waiver_allowed`. `:463-468` converts FAIL→WAIVED only when `waivable_fail AND raw_status == FAIL AND name in mandatory_children AND waiver_allowed`. |
| `:520-559` | `promote_aggregate` — thin wrapper returning only the aggregate. |

### 1.2 How the decision to honor/reject a waiver is actually made

There are exactly **two** mechanisms, and **only one of them is reachable from production code**:

**(1) The single production honor/reject site — `map_acceptance.py`.**

`ultimate_pipeline/quality/map_acceptance.py` imports the strict helper at `:26-29` and uses it at
exactly one place:

```python
1050:                waiver = component_reachability_waiver
1051:                waivable = isinstance(waiver, str) and bool(waiver.strip())
1052:                if waivable and production_gate_waiver_allowed(
1053:                    {"component_reachability": waiver}, "component_reachability"
1054:                ):
1055:                    metrics["component_reachability_waiver_applied"] = True
1056:                    metrics["component_reachability_spec_status"] = QualityStatus.WAIVED.value
1057:                    soft_warnings.append({...})
1068:                else:
1069:                    hard_fail_reasons.append({...})
```

The waiver parameter is declared at `map_acceptance.py:577` (`component_reachability_waiver: str |
None = None`) and documented at `:979-980`. Every other gate in `build_map_acceptance` appends
straight to `hard_fail_reasons` with no waiver branch at all (`:599, 618, 632, 642, 655, 699, 713,
735, 751, 773, 796, 809, 826, 842, 855, 910, 935, 1018, 1069`). `valid_for_experiments` is then
`len(hard_fail_reasons) == 0` at `:1080`, and `failed_gates` is the projected gate-name list at
`:1106`.

**(2) `promote_aggregate` / `promote_aggregate_detailed` — has ZERO production callers.**

A repo-wide search (`Select-String` over every `.py` under `ultimate_pipeline/`, `tools/`, `scripts/`)
for `promote_aggregate` returns hits **only** inside `stage_contracts.py` itself and inside
`ultimate_pipeline/tests/unit/test_waiver_taxonomy.py`. Likewise `enforce_taxonomy=True` appears only
in that test file. `GATE_CLASS_REGISTRY` and `classify_gate` are referenced only by
`stage_contracts.py` and the test. **The aggregate reducer with the taxonomy wired in is currently a
tested-but-unwired capability.**

### 1.3 What is NOT in the waiver path

For completeness on Step 3's buckets — the checks GAP-037's 10 categories describe live in modules
that **never import the waiver system at all**. Confirmed by grep across `ultimate_pipeline/`: zero
`waiv*` matches in `ultimate_pipeline/tools/repo_health.py`,
`ultimate_pipeline/utils/run_provenance.py`, `ultimate_pipeline/utils/finalize_run_pack.py`,
`ultimate_pipeline/tools/pack_lint.py`, `ultimate_pipeline/carla_tools/map_runtime_identity.py`,
`ultimate_pipeline/contracts/gate_runner.py`, `ultimate_pipeline/governance/inputs_manifest.py`.

### 1.4 Registry key vs. real gate-name coverage (important)

I diffed the 24 `GATE_CLASS_REGISTRY` keys against the gate-name strings actually emitted by the two
production gate consumers (`map_acceptance.py` `"gate": "..."` literals and
`quality_gate_manager.py` `self.fail/self.passed("...")` literals):

- **Intersection: 4 of 24** — `component_reachability`, `junction_integrity`, `lane_connectivity`,
  `lane_section_successors`.
- **Registry-only, never emitted anywhere: 20** — `artifact_fingerprint`, `candidate_identity`,
  `carla_runtime_identity`, `carla_structural_compatibility`, `cook_manifest_identity`,
  `deterministic_provenance`, `elevation_quality`, `geometry_continuity`, `lane_link_targets_exist`,
  `lane_width`, `manifest_digest`, `map_registry_identity`, `package_identity`, `repository_sha`,
  `required_artifact_presence`, `runtime_map`, `runtime_map_identity`, `topology_spec`, `xodr_sha`,
  `xodr_xml_integrity`. (These are *descriptive names*; several match YAML gate ids in
  `PRODUCTION_MAP_QUALITY_CONTRACT.yaml`, e.g. `xodr_xml_integrity` at `:60`, `map_registry_identity`
  at `:74`.)
- **Real-but-unregistered: 20** — `carla_opendrive_compat`, `collision_mesh`, `dem_coverage`,
  `elevation_continuity`, `elevation_missing_and_cliffs`, `elevation_seams`, `elevation_smoothness`,
  `enrichment_completeness`, `geometric_continuity`, `lane_count_changes`,
  `lane_geometry_continuity`, `lane_width_continuity`, `length_invariant`, `origin_sanity`,
  `physics_feasibility`, `randomness_entropy`, `semantic_completeness`, `semantic_overlap`,
  `xml_integrity`, `xodr_strict_carla`.

Note two near-miss naming inconsistencies that matter if anyone wires this up:
`geometry_continuity` (registry) vs `geometric_continuity` (emitted, `map_acceptance.py:642`);
`lane_width` (registry) vs `lane_width_continuity` (emitted, `:797`); `elevation_quality`
(registry) vs the four separate emitted `elevation_*` names. Unregistered names fail closed to
non-waivable under `production_gate_waiver_allowed`, so this is safe-by-default but is a live trap
for anyone expecting `classify_gate("geometric_continuity")` to resolve.

---

## Step 2 & 3 — The 10 proposed categories, each mapped to a real call site and bucketed

Buckets, per the task's definitions:

- **(a)** existing check that currently **IS** waivable and would need to become non-waivable
- **(b)** existing check that is **already** non-waivable
- **(c)** **no check exists**; would require new detection

### 2.1 wrong artifact identity

**Bucket: (b).**
- Registry entry already exists: `stage_contracts.py:185` `candidate_identity` → `IDENTITY_INTEGRITY`;
  `:181` `map_registry_identity` → `IDENTITY_INTEGRITY`.
- Real check: `ultimate_pipeline/tools/repo_health.py:466` `validate_candidate_manifest`, with the
  XODR-identity binding at `:533-552` (existence `:541-544`, hash `:546-552`) and the CARLA build
  identity at `:554-562`. Returns `IDENTITY_MISMATCH` at `:490`/`:564`.
- Second, independent check: `ultimate_pipeline/carla_tools/map_runtime_identity.py:454`
  `verify_runtime_map_identity`, name layer `:491-498`, structural fingerprint layer `:516-525`.
- Third: `ultimate_pipeline/carla_tools/map_registry.py:1010-1016` raises
  `MapRegistryDriftError` on content drift.
- **Already non-waivable because nothing in these modules consults a waiver at all** (see §1.3).
- Uncertainty: I did not trace every transitive caller of `validate_candidate_manifest`; the only
  call site I read is the CLI path `repo_health.py:653-669`.

### 2.2 hash mismatch

**Bucket: (b).**
- Registry: `stage_contracts.py:184` `manifest_digest`, `:188` `xodr_sha`, `:182`
  `artifact_fingerprint` — all `IDENTITY_INTEGRITY`.
- Real checks: `carla_tools/map_registry.py:1010-1016`; `governance/inputs_manifest.py:167-175`
  (`InputsManifestMismatchError`, explicit "do not proceed with a mismatched input");
  `tools/repo_health.py:546-552`; `utils/finalize_run_pack.py:575-576` (`"hashed artifact
  tampered"`); `tools/pack_lint.py:329-334` (`sha256_manifest_coverage` mismatch);
  `tools/final_map_readiness_gate.py:45-61` `_verify_xodr_binding`.
- Already non-waivable (no waiver consultation in any of these).

### 2.3 corrupt artifact

**Bucket: (b) for the checks; see note.**
- Real checks: `quality/check_xml_integrity.py:36-41` (`parse_error`) and `:27-28`/`:50-58`
  (`missing_file`, header attrs); `utils/finalize_run_pack.py:522-529` (`signature.json is
  unreadable/corrupt`, not-a-JSON-object); `tools/repo_health.py:500-507`;
  `tools/artifact_integrity_check.py:52` `_open_image_ok`.
- `xml_integrity` **is** wired through `quality_gate_manager.py:77-85`
  (`gate_xml_integrity` → `self.fail("xml_integrity", ...)`), which routes through
  `_finalize_gate` (`:58-65`) → `normalize_gate_result` (`stage_contracts.py:604-672`) — a
  **fail-closed dict normalizer with no waiver branch**. So the corruption verdict is already
  unwaivable.
- **Note / partial uncertainty**: `xml_integrity` is one of the "real-but-unregistered" names from
  §1.4. If `production_gate_waiver_allowed` were ever consulted for it, it would fail closed → False
  → non-waivable. So the outcome is correct either way, but via the unknown-name path rather than a
  deliberate classification.

### 2.4 missing required artifact

**Bucket: (b).**
- Registry: `stage_contracts.py:198` `required_artifact_presence` → `STRUCTURAL_INTEGRITY` (never
  emitted as a real gate name — §1.4).
- Real checks: `tools/repo_health.py:519-522` (every `CANDIDATE_REQUIRED_FIELDS` entry from
  `:432-445` must be present and non-empty) and `:495-498` (manifest itself missing);
  `utils/finalize_run_pack.py:567-569` (`"hashed artifact now missing"`);
  `tools/pack_lint.py:274-277` `missing_referenced_prompt` and `:305-308`
  `missing_referenced_module`; `quality/check_xml_integrity.py:32-34` `missing_file`;
  `governance/inputs_manifest.py:153-157` (`ABORT: pinned input not found`) and `:179-189`
  (`unchecked_required` roll-up).
- Already non-waivable.

### 2.5 wrong repository SHA

**Bucket: (b).**
- Registry: `stage_contracts.py:183` `repository_sha` → `IDENTITY_INTEGRITY`.
- Real checks: `utils/run_provenance.py:466-476`
  (`collect_strict_release_provenance`, "expected SHA … but repository HEAD is …"), plus
  `:430-445` branch binding and `:478-484` clean-worktree; `tools/repo_health.py:525-531`;
  `domain_gap_gnn/gnn_provenance.py:450-451` (`mismatch:git_sha`).
- Already non-waivable.

### 2.6 wrong cooked package

**Bucket: (b).**
- Registry: `stage_contracts.py:186` `package_identity`, `:189` `cook_manifest_identity` → both
  `IDENTITY_INTEGRITY` (never emitted — §1.4).
- Real check: `tiling/carla_0916_large_map_contract.py:80-150` `resolve_package_identity` raises
  `PackageBindingError` on empty request `:94-96`, missing dir `:99-102`, missing descriptor
  `:105-110`, bad JSON `:113-116`, non-single `maps` `:117-120`, CLI/map mismatch `:134-139`, and
  xodr-sha disagreement between descriptor and `*.large_map_package.json` `:143-149`.
- Already non-waivable.

### 2.7 wrong runtime map

**Bucket: (b).**
- Registry: `stage_contracts.py:200-202` `runtime_map_identity`, `carla_runtime_identity`,
  `runtime_map` → all `RUNTIME_DEPENDENT`.
- Real checks: `carla_tools/map_runtime_identity.py:491-498` (canonical-name layer, explicitly not a
  substring test per the docstring `:469-471`) and `:516-525` (structural fingerprint);
  `core/carla_opendrive_loader.py:66` and `:80` raise
  `RUNTIME_MAP_IDENTITY_MISMATCH`; `perception/record_route_fixed.py:1897`;
  `tools/repo_health.py:466-565` (`runtime_map` is a required manifest field, `:444`).
- Already non-waivable. `runtime_map` is also a real key in the adversarial matrix fixture
  (`ultimate_pipeline/tests/adversarial/test_v5_adversarial_matrix.py:92`) and
  `ultimate_pipeline/tests/unit/test_runtime_identity_gate.py:49,245`.

### 2.8 manifest tampering

**Bucket: (b).**
- Registry: `stage_contracts.py:184` `manifest_digest` → `IDENTITY_INTEGRITY`.
- Real check: `utils/finalize_run_pack.py:498-602` `verify_run_pack` — per-artifact tamper
  detection `:562-576`, in-manifest `signature_sha256` recomputation `:540-550`, path-escape
  `:564-566`, and the `SUCCESS.txt`↔manifest digest binding `:578-599`. Function docstring `:499-502`
  states its purpose verbatim: "Detects post-finalization tampering of a hashed artifact".
- Also `perception/route_manifest.py:196` and `:243` emit `route_manifest_digest_mismatch`.
- Already non-waivable.

### 2.9 schema corruption

**Bucket: (b), with the weakest wiring of the ten.**
- Registry: `stage_contracts.py:191` `xodr_xml_integrity` → `STRUCTURAL_INTEGRITY` (never emitted as
  a real gate name — §1.4). **There is no `schema`/`xsd` key in `GATE_CLASS_REGISTRY`.**
- Real check: `quality/check_xodr_schema.py:90-174` `validate_xodr_schema_structured`, with honest
  statuses `PASS / FAIL / INCOMPLETE_DEPENDENCY / NOT_CONFIGURED` and explicit refusal to treat
  un-checked as pass (`:114-122` no XSD; `:123-131` lxml missing; `:134-141` XSD file missing;
  `:151-158` `xsd_input_unparseable`; `:167-174` `xsd_conformance`). Plus
  `check_xml_uniqueness` at `:31-70` (duplicate road/lane ids).
- **Honest finding: this check is NOT a blocking gate.** Its only production call site is
  `pipeline_stages/stage_08_integrity.py:911-921`, which **prints** the violation and writes it to
  `vreport` under key `"xodr_schema"` — it does **not** raise, does not append to any hard-fail list,
  and does not feed `map_acceptance.build_map_acceptance` (I grepped `map_acceptance.py` for
  `xml_integrity|xodr_schema|xsd`: **zero matches**). Secondary callers
  `tools/crash_safe_length_repair.py:299-322` and `tools/verify_final_xodr.py:228-314` are
  diagnostic. So while the check is *not waivable* (nothing waives it), it is also not *enforced* —
  it can neither be waived nor can it block. Whether that counts as "(b) already non-waivable" or as
  a fourth bucket ("unwaivable because unwired") is a judgement call I am flagging rather than making.

### 2.10 invalid cryptographic digest

**Bucket: (b).**
- Registry: covered by `stage_contracts.py:184` `manifest_digest` and `:182`
  `artifact_fingerprint`.
- Real checks: `utils/finalize_run_pack.py:541-550` (aggregate `signature_sha256` recomputation
  over the file map — "manifest `signature_sha256` does not match its own file map");
  `:586-592` (`SUCCESS.txt` bound `manifest_sha256` vs on-disk);
  `:593-597` (bound `signature_sha256` vs recomputed);
  `tools/repo_health.py:510`/`:546-547` (manifest and XODR digests recomputed).
- Already non-waivable. Caveat: the whole run-pack mechanism is **SHA-256 content hashing, not
  signature cryptography** — no public-key/HMAC verification of `signature.json` exists in
  `finalize_run_pack.py` (the writer is `write_signature_json` at `:617-627`, the digest is computed
  at `:112` `hash_file_sha256`). "Invalid cryptographic digest" in the cryptographic sense has **no
  check**; in the SHA-256-integrity sense the checks above exist and are non-waivable.

### 2.11 Bucket tally

| Bucket | Count | Categories |
| --- | --- | --- |
| (a) exists, currently waivable, must become non-waivable | **0** | — |
| (b) exists, already non-waivable | **10** | all ten (with caveats on #9 "unwired" and #10 "hash integrity, not crypto") |
| (c) no check exists | **0** | — |

**Zero categories fall into (a).** This is the single most important scoping result: there is no
currently-waivable integrity check that would need converting, because the taxonomy was already
built to make all of them non-waivable (`627afe9f`) and, more fundamentally, because **the only
waiver-honoring code path in the entire production tree is the `component_reachability` branch at
`map_acceptance.py:1050-1067`** — a `QUALITY_DEVIATION`-classified gate.

The two caveats that could arguably push a category toward a "check needed" reading are stated in
§2.9 and §2.10 and are flagged as uncertainty, not resolved.

---

## Step 4 — Diff-size estimate

Because the taxonomy, registry, fail-closed resolver, and green tests already exist, the remaining
work is **wiring and coverage, not design**. Estimates are for a *minimal* change that makes each
category structurally non-waivable at a point where a waiver could actually be applied. Line counts
are my honest estimates, not measurements; I did not write the code.

### 4.1 Per-category

| # | Category | Minimal change | Est. lines |
| --- | --- | --- | --- |
| 1 | wrong artifact identity | registry keys already present (`:181,:185`); needs an emission site that actually consults the taxonomy | 5–15 |
| 2 | hash mismatch | registry keys already present (`:182,:184,:188`); same | 5–15 |
| 3 | corrupt artifact | `xml_integrity` unregistered → add key to `GATE_CLASS_REGISTRY` (1 line) or rely on fail-closed unknown | 1–5 |
| 4 | missing required artifact | `required_artifact_presence` already registered (`:198`) but never emitted; add key/emission | 1–5 |
| 5 | wrong repository SHA | key already present (`:183`); needs emission site | 5–15 |
| 6 | wrong cooked package | keys already present (`:186,:189`); needs emission site | 5–15 |
| 7 | wrong runtime map | keys already present (`:200-202`); needs emission site | 5–15 |
| 8 | manifest tampering | key already present (`:184`); needs emission site | 5–15 |
| 9 | schema corruption | **new**: no `schema`/`xsd` key exists; needs key + an enforcement site (`stage_08_integrity.py:911-921` currently only prints) | 10–25 |
| 10 | invalid cryptographic digest | key present via `manifest_digest`; if *cryptographic* (keyed) verification is meant, that is **net-new** detection, far larger | 5–15 (SHA-256 sense) / 80–150 (true-crypto sense) |

**Subtotal, SHA-256-integrity reading of #10: ~48–140 lines.**
**Subtotal, true-cryptographic reading of #10: ~123–275 lines.**

### 4.2 Total

| Scope | Total |
| --- | --- |
| Minimal (registry coverage only; all ten already fail closed via the unknown-name path) | **~10–30 lines** |
| Moderate (register the real emitted gate names so classification is deliberate rather than accidental) | **~50–120 lines** |
| Moderate + wire `enforce_taxonomy` into at least one live aggregate call site | **~90–200 lines** |
| + new schema-corruption enforcement (`stage_08_integrity.py`) | **~100–225 lines** |
| + true cryptographic signature verification for #10 | **~180–375 lines** |

Plus **tests**: `ultimate_pipeline/tests/unit/test_waiver_taxonomy.py` is 150 lines today;
covering 10 categories × (registry membership + classification + aggregate refusal) is roughly
**60–120 added test lines**, and `tests/unit/test_stage_contracts_aggregate.py` (335 lines) may need
new cases if `enforce_taxonomy` defaults change.

### 4.3 Refactor opportunity — strongly favours one enum + one enforcement point

**One category enum + one enforcement point is clearly the right shape, and the code is already
built for it.** The evidence:

1. `GateClass` (`:158-165`) + `NON_WAIVABLE_CLASSES` (`:168-174`) + `classify_gate` (`:211-219`) +
   `production_gate_waiver_allowed` (`:301-326`) already form a **single choke point**: every
   classification question in the codebase routes through `classify_gate`, and every
   honor/reject question routes through `production_gate_waiver_allowed`.
2. `classify_gate` already **fails closed on unknown names** (`:211-219`), and
   `production_gate_waiver_allowed` already returns `False` for unknown (`:318-320`). **This means
   the 20 real-but-unregistered gate names from §1.4 are *already* non-waivable today** without a
   single new line. Per-category scattered edits would be strictly more work and strictly more risk
   for the same security outcome.
3. The taxonomy was deliberately designed as an **opt-in switch** (`enforce_taxonomy`, `:359`,
   `:449`) precisely so a single call site can be flipped to strict mode without touching the rest.
4. The registry is **name-keyed, not position-keyed** (`:179-208` is a `Dict[str, GateClass]`), so
   adding categories is pure data.

**Where scattered edits WOULD be required** (this is the honest counterweight): the registry is keyed
by *gate name*, but the 10 categories are keyed by *defect class*. One gate can raise several of the
10 (`repo_health.validate_candidate_manifest` alone raises: manifest-not-found, manifest-corrupt,
schema-mismatch, missing-required-field, repo_sha-mismatch, xodr-missing, xodr-hash-mismatch,
CARLA-version-mismatch — i.e. categories 1, 3, 4, 5, 9, 10). A name-keyed registry cannot express
"this *specific defect* inside this gate is non-waivable while another defect in the same gate is
waivable". Adding that granularity requires a **defect-level taxonomy** (defect code → category),
which does not exist today and would be a materially larger change than any number in §4.2. I flag
this as scope uncertainty, not a recommendation.

---

## Step 5 — Interaction with tally-all/fail-at-end and `failed_gates`

### 5.1 `CumulativeGateRunner` is structurally waiver-blind

`ultimate_pipeline/contracts/gate_runner.py` (75 lines):
- `:19-30` — class docstring: **"Tally-all, fail-at-end gate runner. Every gate runs regardless of
  prior failures. When *finalize()* is called and the runner is in strict mode, a single
  RuntimeError is raised listing every gate that failed."**
- `:32-58` `run()` — executes `fn()`, normalizes via `normalize_gate_result` (`:40`), and on
  exception records `{"ok": False, "error": ...}` (`:56`). Every gate is appended to
  `self.results` regardless of outcome.
- `:60-75` `finalize()` — `failed = [r for r in self.results if not r.ok]`; **only here** does
  strict mode raise, as one aggregated `RuntimeError`.

`GateRunRecord` (`:10-16`) carries only `(stage, gate, ok, detail, elapsed_s)`. **There is no
waiver field and no gate-class field in the record**, and `gate_runner.py` does not import anything
from `stage_contracts.py` except `normalize_gate_result` (`:7`).

Callers: `main_pipeline.py:3323-3349` `_stage_gate` (docstring `:3330` "Delegates to
CumulativeGateRunner (tally-all, fail-at-end)") and `:3351-3365` `_finalize_gates` (docstring `:3352`
"Call at the end of the pipeline to raise on any collected failures").

### 5.2 Does non-waivable need to fail IMMEDIATELY?

**On the evidence read, no — and the current code already demonstrates that.** Reasoning, cited:

1. **Non-waivable and fail-fast are independent properties in this codebase.** The taxonomy's effect
   is entirely at the *waiver-conversion* step (`stage_contracts.py:463-468`), which happens *after*
   a FAIL is produced. `_worst_of` (`:233-262`) then reduces FAIL to the top of the aggregate. So a
   non-waivable gate simply never enters the WAIVED bucket; it still flows through the same
   fail-at-end aggregation. The only "immediate" behaviour in the whole waiver system is
   `map_acceptance.py:1052`'s if/else — which is a *branch at append time*, not an early exit: on
   failure to obtain a waiver it appends to `hard_fail_reasons` at `:1069` and execution continues
   to `:1080`'s `valid_for_experiments` computation and `:1106`'s `failed_gates` projection.
2. **`failed_gates` is a projection, not a control point.** `map_acceptance.py:1106`
   `payload["failed_gates"] = [item["gate"] for item in hard_fail_reasons]` — it is derived *after*
   the full tally. Downstream, `contracts/artifact_authority.py:801` only *copies* it into the
   receipt (`"failed_gates": acceptance.get("failed_gates", [])`). Nothing branches on it.
3. **The one place an early exit *is* used today is a RuntimeError from a different subsystem**:
   `main_pipeline.py:3182-3186` raises when `build_map_acceptance` itself throws, and
   `:3198-3206` raises when the fingerprint is not written. Those are *exception paths*, not
   gate-class paths.
4. **Counter-consideration, stated honestly:** if a non-waivable category were given an
   early-abort semantic, it would have to be implemented at a layer that does not currently exist —
   `CumulativeGateRunner.run` (`:32-58`) has no early-exit branch and no notion of a gate class, and
   `_finalize_gates` (`:3351`) is only reached at pipeline end. Making it immediate would mean
   adding class-awareness to `gate_runner.py` **and** deciding what to do with the already-collected
   `self.results` (currently reported as a count + list in `cumulative_gate_report.json`,
   `main_pipeline.py:3359-3362`). That is a behavioural change to the runner's documented contract
   (`gate_runner.py:21-25`), not a taxonomy change. I am not asserting it is needed; I am noting
   that the existing model does not provide it and nothing currently asks for it.

---

## What I did not verify / open questions

- I did **not** run the full test suite (read-only scoping; a 14-test focused run was the only
  execution). No claim is made that the wider suite is green.
- I did **not** trace all transitive callers of `validate_candidate_manifest`,
  `verify_runtime_map_identity`, or `verify_run_pack`; I read their definitions and the one or two
  call sites named above.
- I did **not** verify whether any CI workflow or `tools/` driver passes a waiver to
  `build_map_acceptance`. I searched for `build_map_acceptance` and
  `component_reachability_waiver` across `ultimate_pipeline/`; the only two call sites are
  `main_pipeline.py:3170-3176` and `tools/run_thesis_final_experiments.py:171-176`, and **neither
  passes `component_reachability_waiver`** (it defaults to `None` at `map_acceptance.py:577`). I
  did not search `.github/` or shell scripts for invocations.
- Whether "invalid cryptographic digest" (§2.10) means *SHA-256 content integrity* (checks exist,
  bucket b) or *keyed/asymmetric signature verification* (no check exists) is a **specification
  ambiguity I cannot resolve from the code**. Both readings are reported.
- Whether schema corruption (§2.9) belongs in bucket (b) "already non-waivable" or in a separate
  "unwaivable because unwired" bucket is a judgement call; the facts (check exists, is not
  enforced, is not waived) are stated and the judgement is left open.

---

## Verification commands run

```
python -m pytest ultimate_pipeline/tests/unit/test_waiver_taxonomy.py -q
  → 14 passed in 1.89s

git log --oneline -1 627afe9f
  → 627afe9f fix(governance): make integrity gates structurally non-waivable (NEW-210/GAP-037)
git merge-base --is-ancestor 627afe9f HEAD
  → ANCESTOR
git log --oneline -3 -- ultimate_pipeline/contracts/stage_contracts.py \
      ultimate_pipeline/tests/unit/test_waiver_taxonomy.py

git status --porcelain          (read-only; observed 10 modified tracked files, none mine)
git log --oneline -5            (baseline tip f6af647a)
```

Grep/Select-String sweeps (read-only): `(?i)waiv` across `ultimate_pipeline/`; `waiv*` across
`ultimate_pipeline/`, `tools/`, `scripts/`; `promote_aggregate` / `enforce_taxonomy` /
`GATE_CLASS_REGISTRY` / `classify_gate` / `production_gate_waiver_allowed` across the whole repo
excluding `.venv/` and `build/`; `xml_integrity|xodr_schema|xsd` in `map_acceptance.py` and
`quality_gate_manager.py`; `allows_waived|PRODUCTION_MAP_QUALITY_CONTRACT` across all `.py`
(zero matches).
