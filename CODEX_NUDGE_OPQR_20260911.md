# Codex — priority nudge: O, P, Q, R next

Everything sent since (Wave 2/3 follow-ups, GAP-018, Phase J wiring, semantic-overlap strict-mode,
lane-count-change gate, turn/cycle lanes, GAP-024, lanelink-turn-restriction-awareness,
OSM-access-restrictions) has landed and been independently verified. Good work -- all 8 checked
out genuine, no discrepancies found. Fix 1 and Fix 2 are also both resolved.

Four items have been queued for a while now with zero pickup: PROMPT O, P, Q, R. These are the
highest-value findings from the phase_* wiring audit (Phase H, Phase G6, Phase F5, and the
Phase G-family survey) -- please prioritize these next, in this order:

## 1. PROMPT O (do first) — native signal enrichment
File: CODEX_NATIVE_SIGNAL_CORRECTION_20260909.md (architecture/production-map-quality-20260906
branch). A real, tested, large-scale-validated signal-enrichment system
(ultimate_pipeline/signals/native_signal_enrichment.py, wrapping Phase H) is already wired into
stage_08_integrity.py but gated behind a Settings attribute that doesn't exist
(ENABLE_NATIVE_SIGNAL_ENRICHMENT). Old evidence shows 3309 speed-limit updates, 158 zone-sign
updates, 212 turn-lane updates on a real full-scale run. Investigate-first: reproduce fresh
against the current map, confirm no real reason it was left off, resolve the stage-4 overlap,
wire it on if clean.

## 2. PROMPT Q — F5 elevation-seam solver
File: CODEX_PROMPT_Q_F5_ELEVATION_SOLVER_20260909.md. A graph-relaxation elevation-seam solver
with real evidence (seam delta 5.129m -> 3.036m, zero over-threshold after, on a real 45,632-seam
run) sits unwired while the live approach has a documented weakness on junctioned/cyclic
topology. Confirm the algorithmic relationship to what's live, reproduce fresh, head-to-head
compare, propose integration if it holds up.

## 3. PROMPT R — Phase G-family survey
File: CODEX_PROMPT_R_G_FAMILY_SURVEY_20260909.md. Read-only survey of G1-G5/G7 (lane inventory,
polynomial validation, cross-section, continuity, type reclassification, roadmark semantics) --
rank them by real findings against the CURRENT map so the next individual deep-dive can be
prioritized with evidence, not guesswork. Do this before P if possible, since G6 (below) is part
of the same family and the survey's context may be useful background, though P can also proceed
independently if that's more efficient.

## 4. PROMPT P — G6 lane-coverage repair (read the full context first, this one is sensitive)
File: CODEX_PROMPT_P_G6_ISOLATED_LANES_20260909.md. This touches a topic that was investigated
three times in an earlier session and definitively closed -- read the MANDATORY CONTEXT section
at the top of that file in full before starting anything. It is investigation-first only: the
task is explicitly NOT to modify the map-of-record or wire anything in, just to produce a
trustworthy answer (with real numbers) on whether this candidate technique genuinely helps, for
human review.

For all four: same discipline as everything else this session -- verify source authority, work on
an isolated branch, real evidence over hand-authored claims, full offline tests green, report
honestly if something doesn't hold up on fresh verification even if the old evidence looked good.
