# CODEX B3 — Content-addressed manual-map registry (pin the reference for RQ1) (R3)

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: ./.venv/Scripts/python.exe · UP_DISABLE_CARLA=1
MODEL: Codex 5.x HIGH. Prereq for B4. Independent of A/E.

## Problem
The auto-vs-manual domain-gap comparison's validity depends on using the CORRECT manual reference. There is
provenance drift: a file named `manual_ingolstadt_grid0828.xodr` in some worktrees actually contains Grid0821
content (993r/119j/5000sig/2553elev) vs true Grid0828 (972r/119j/4981sig/2507elev). Comparing against the wrong
manual map silently invalidates RQ1.

## Goal
A content-addressed registry that pins each manual reference by FULL sha256 + verified content signature, rejects
mislabeled/ambiguous files, and never silently falls back between Grid0821 and Grid0828.

## Steps
1. Adapt/extend the existing registry (ultimate_pipeline/carla_tools/map_registry.py) to register the manual
   references AUTO_INGOLSTADT (the OSM-auto map used for RQ1), GRID0821, GRID0828 — each by full sha256 and a
   content signature (road/junction/signal/elevation counts).
2. Reject a file whose NAME implies one grid but whose CONTENT signature matches another (the drift case).
3. Locate the authoritative copies across the worktree family; record their sha256 + counts in the registry;
   choose the canonical manual reference for RQ1 and DOCUMENT the choice (do not guess silently — if ambiguous,
   ESCALATE_TO_CLAUDE with the candidates + signatures).
4. Tests: registry resolves each map by sha256; the name↔content-mismatch case is REJECTED; no silent Grid fallback.

## Boundaries
- Do NOT mutate any .xodr. Registry + tests + report only. Large maps are sha256-anchored, not committed.

## Deliverables / git
Registry code + tests; report reports/post_audit_hardening/B3_MANUAL_MAP_REGISTRY.md/.json (per-map sha256 +
signatures + chosen canonical reference). Atomic commits; push; local==remote; suite green.
Verdict: MANUAL_REF_PINNED | PARTIAL | BLOCKED_NEEDS_DECISION.
