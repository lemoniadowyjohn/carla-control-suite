# Codex — CORRECTION to PROMPT M + new PROMPT O (2026-09-09, continued discovery)

## Correction notice

PROMPT M (committed 2026-09-08, "regulatory_sign_writer.py is fully wired and fully dead
simultaneously") was based on an incomplete picture. Everything in it was factually accurate
(SIGN_TABLE really does match 0/50 real streets, the docstring really was stale) -- but further
digging found something PROMPT M didn't know about: a SECOND, more capable signal-enrichment
system already exists, is already wired into the live pipeline, and already has real
large-scale execution evidence proving it works. This changes the right fix. Do PROMPT O below
INSTEAD of (or as well as, see task 3) PROMPT M's SIGN_TABLE-expansion suggestion.

## PROMPT O — wire on the native (Phase H) signal enrichment system; it's real, tested, and dark

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/native-signal-enrichment-v1-<date>.

CONFIRMED (2026-09-09): ultimate_pipeline/signals/native_signal_enrichment.py::
apply_native_signal_enrichment wraps a genuine, sophisticated, spatially-aware, provenance-
tracked signal system (ultimate_pipeline/tools/phase_h0_osm_signal_extract.py through
phase_h3_signal_integrity.py -- OSM extraction with CRS-verified native-frame projection,
road matching, speed-limit/zone-sign/turn-lane writing with conflict rejection, and an integrity
audit). It is genuinely called from the live pipeline
(ultimate_pipeline/pipeline_stages/stage_08_integrity.py:834), NOT dead code.

But it is gated behind a flag that cannot ever be true by default:
    enabled = _env_truthy("UP_ENABLE_NATIVE_SIGNAL_ENRICHMENT") or bool(
        getattr(settings_obj, "ENABLE_NATIVE_SIGNAL_ENRICHMENT", False)
    )
`ENABLE_NATIVE_SIGNAL_ENRICHMENT` is not a declared attribute anywhere on the Settings class
(confirmed: `hasattr(Settings(), "ENABLE_NATIVE_SIGNAL_ENRICHMENT")` is False), and
`UP_ENABLE_NATIVE_SIGNAL_ENRICHMENT` is not set in .env.example or any named release profile.
So in every default/documented run, this entire system is unreachable.

This matters because it is NOT experimental or unproven -- real execution evidence exists at
production scale: reports/post_audit_hardening/20260804T050000Z/PHASE_H_SIGNAL_ENRICHMENT.json
shows, on a real run: 4314 matched roads, 3309 roads updated with speed limits (3771 speeds
inserted), 158 roads updated with zone signs, 212 roads updated with turn lanes, 40 conflicting
candidates correctly rejected (not silently applied), 52071 legacy/stale speed entries cleaned
up, zero unprovenanced writes, crs_verdict OSM2ODR_NATIVE_VERIFIED. Compare this to the current
DEFAULT path (stage_04_enrichment.py's apply_regulatory_signs/apply_speed_limits/apply_turn_lanes,
name-matched, no conflict detection, no CRS/provenance verification), which -- per a separate
finding this session -- produces exactly 0 regulatory sign objects on the current map because its
SIGN_TABLE doesn't cover this dataset's actual sign codes.

TASK:
1. Confirm the 20260804 evidence is still reproducible against the CURRENT pinned map-of-record
   and CURRENT phase_h*.py code (not stale/from a since-changed codebase state) -- actually run
   apply_native_signal_enrichment against the real pinned map and OSM source and report fresh
   numbers, don't just cite the old report.
2. Determine whether there's a real reason this was left disabled (check git blame/log on the
   `_apply_optional_native_signal_enrichment` gating logic and the phase_h*.py modules for any
   documented caveat, known issue, or performance concern -- a 52071-legacy-speed-removal count on
   one run suggests this could be slow/heavy at full scale; measure and report actual wall-clock
   time). If you find a real reason it was never turned on, document it clearly. If you find no
   reason (most likely, given the evidence quality), that itself is the finding -- a working
   system was simply never flagged on.
3. Resolve the overlap with stage 4's writers explicitly: apply_native_signal_enrichment's
   remove_legacy_speeds step suggests it's designed to run AFTER and clean up stage 4's weaker
   speed-limit writes -- confirm this actually works correctly when both stages run in sequence
   (which is the current default: stage 4's speed_limit_writer.py always runs, stage 8's native
   enrichment currently never does). Regulatory signs are a separate concern: stage 4's
   apply_regulatory_signs writes <object> elements (currently always empty per SIGN_TABLE
   mismatch), Phase H's write_zone_signs writes <signal> elements -- confirm these don't
   conflict/duplicate if both are ever active, and note whether stage 4's (currently no-op)
   regulatory-sign <object> writer becomes fully redundant once native enrichment is on (in which
   case PROMPT M's SIGN_TABLE-expansion task becomes unnecessary -- report which is actually true).
4. If step 1's fresh run and step 2's investigation both come back clean, add ENABLE_NATIVE_SIGNAL_ENRICHMENT
   as a real, declared Settings attribute (not just an env-var-only escape hatch) and enable it in
   whichever release profile(s) represent the actual production/perception-release path, following
   this codebase's existing pattern for feature flags. Do NOT flip it on for EVERY profile
   unconditionally without checking whether e.g. EXPERIMENTAL_UNSAFE or DEVELOPMENT profiles have
   a reason to keep it off. Re-run the full offline suite and scripts/measure_candidate_acceptance.py
   against the pinned map before/after, report the diff.

This is real, evidenced work -- but it's also a bigger structural change (enabling a system that
touches 3000+ roads' worth of output) than most prompts this session. If step 1's fresh
reproduction doesn't match the old evidence, or step 3's overlap check finds a real conflict,
STOP and report rather than enabling it anyway.

End with:
FRESH_REPRODUCTION: MATCHES_OLD_EVIDENCE | DIVERGES (explain) | FAILED (explain)
DISABLE_REASON_FOUND: YES (explain) | NO
STAGE4_OVERLAP_RESOLUTION: <what you found and did>
ENABLED_BY_DEFAULT: PASS | FAIL | NOT_DONE (explain why not)
MAP_OF_RECORD_ACCEPTANCE_DELTA: <diff summary or "no measurable change">
FULL_OFFLINE_TESTS: PASS | FAIL
FIRST_BLOCKER: <one exact blocker or NONE>
```

## PROMPT M's remaining task (do only after PROMPT O resolves the overlap question)

If PROMPT O's step 3 finds that Phase H's `write_zone_signs` genuinely makes stage 4's
`apply_regulatory_signs` fully redundant, PROMPT M's SIGN_TABLE-expansion task becomes
unnecessary -- close it as superseded rather than doing the work. If PROMPT O finds native
enrichment should NOT be turned on (a real blocking reason found), then PROMPT M's original task
(fix the stale docstring, investigate SIGN_TABLE coverage) remains the right fallback -- do it
then.

## PROMPT N is unaffected by this correction

Confirmed: phase_h0_osm_signal_extract.py has zero references to traffic_signals/controller
candidates (the evidence JSON's own counters show "controller": 0 requested). Native signal
enrichment does not cover traffic-light ground-truth correlation at all. PROMPT N (traffic-light
inference vs. the 44 real highway=traffic_signals nodes) remains a fully separate, still-valid
task regardless of what happens with PROMPT O.
