# AG07 — Architecture Gate Verdict

> **RE-VERIFICATION 2026-07-31 (fresh Opus 4.8, read-only gate re-run) @ HEAD `d4b0fe14`.**
> Primary verdict is **UNCHANGED: `REQUIRES_BASE_CORRECTION`; CODEX 5.5 NOT authorized.**
> **Delta vs. first run (@ `5eddcc54`): B1 is now CLOSED** — P2 fresh-hook test passed (`FCH01` PASS @ `b6c09340`,
> `GOV-HOOK-001 = RESOLVED`), so the `FAIL_HOOK_GOVERNANCE` sub-condition is **CLEARED**. The three post-P4 commits
> (`867811c4`, `1884d9d0`, `d4b0fe14`) are **governance-only** and do **not** close B2/B3/B4. The gate still blocks on
> `BLOCKED_TOOLCHAIN` (B4) + missing authoritative inputs (B2 CRITICAL, B3). Rows updated below are marked `[re-verified 07-31]`;
> the original 07-30 first-run text is otherwise preserved for audit.

## Primary verdict: `REQUIRES_BASE_CORRECTION`

Remaining sub-condition that independently blocks approval: `BLOCKED_TOOLCHAIN` (cook-path). `FAIL_HOOK_GOVERNANCE` is **CLEARED** as of the 07-31 re-verification (B1 closed). **CODEX 5.5 is NOT authorized.**

The authority chain is clean (AG01) and the architecture is unambiguous — **current `A_RUNTIME_XODR_ONLY` → target `E_COOKED_LOADABLE_CUSTOM_MAP` (Track A, UE4.26/0.9.16)** — so this is **not** `REQUIRES_ARCHITECTURE_DECISION` or `G`. The gate blocks on **base-input completeness and a governance prerequisite**, not on architectural ambiguity.

## 1. Pending-prompt status — actual (verified), not asserted

| Prompt | Asserted | **Verified reality** | Evidence |
|---|---|---|---|
| P0 | RESOLVED | **CONFIRMED** — branch pushed green; CC01–CC05 committed @ `42f7b77c`; HEAD `5eddcc54` is a docs-only descendant | CC05, git |
| P1 | DONE | **PARTIAL** — DV01–DV04 exist **but `reports/delta_base_verification/` is UNTRACKED** (on disk, not committed) | `git ls-files` (empty) |
| P2 | RESOLVED | **`[re-verified 07-31]` EXECUTED / PASS** — fresh Haiku 4.5 session; `FCH01` PASS committed @ `b6c09340`; 6 hook events, no `python3` failures; `GOV-HOOK-001 = RESOLVED` | `FCH01`, ledger |
| P3 | READY / BASE_READY | **SUBSTANTIALLY DONE, CONDITIONAL** — `agent_sync.yaml`+ledger+lock landed (`634e94ec`), BC01–BC06 committed (`698a7d9f`); **but BC06 itself lists P2 as not-done and leaves FINAL SHA a placeholder** | BC06 |
| P5 | BLOCKED | **CONFIRMED BLOCKED** — `C55_08 = BLOCKED_INVALID_BASE` @ `0e6e652e`; no commit, no map mutation; outputs untracked/stale | C55_08 |

**Net:** P0 ✔, P1 evidence-untracked, **P2 ✔ met `[re-verified 07-31]`**, P3 done (P2 condition now satisfied), P5 correctly blocked.

## 2. Blockers (must close before `ARCHITECTURE_APPROVED_FOR_CODEX_55`)

| ID | Blocker | Severity | Exact closure action | Proof of closure |
|---|---|---|---|---|
| ~~**B1**~~ | ~~P2 fresh-session hook test never ran (`FAIL_HOOK_GOVERNANCE`)~~ | ✅ **CLOSED `[07-31]`** | *(done)* fresh Haiku 4.5 ran P2; `FCH01` PASS @ `b6c09340`; `GOV-HOOK-001 → RESOLVED` | `FCH01_hook_events.md` (6 events, no `python3` failures) |
| **B2** | Authoritative XODR not pinned | **CRITICAL** | Pin a real, tracked, hashed input XODR (not the `structural_gap_run11` results artifact); record `<geoReference>`/CRS | tracked `*.xodr` + SHA + registry entry |
| **B3** | Authoritative FBX / visible-road source absent | **HIGH** | Provide FBX describing the same map, **or** record a `CARLA_GENERATED_ROAD` decision that drops the FBX requirement | tracked decision + (if FBX) input hash |
| **B4** | Cook toolchain absent on host (`BLOCKED_TOOLCHAIN`) | **HIGH** | Stand up CARLA 0.9.16 + UE4.26 **source** build on Linux/WSL2+Docker; pin CARLA/UE commits + image digest | successful `make` build log + digest |
| B5 | `osm/`,`tiling/`,`perception/` source-absent (only `.pyc`) | MEDIUM | Restore/commit the subsystem source or formally deprecate it | tracked `.py` or DEPRECATED note |
| B6 | P1 & P5 evidence untracked | LOW | Commit `delta_base_verification/` (and regen P5 when authorized) or mark ephemeral | `git ls-files` shows tracked |

Blockers B1–B4 were the ones that kept this a `REQUIRES_BASE_CORRECTION` rather than an approval. **`[07-31]` B1 is now closed**, but **B2 (CRITICAL) + B3 + B4 remain open**, so the primary verdict stands unchanged. B2 alone (no pinned authoritative XODR) is now the dispositive base-input blocker; B4 independently keeps `BLOCKED_TOOLCHAIN` active.

## 3. Thesis boundary (explicit)

- **Historical thesis evidence** — `submission/results/structural_gap_run11/` (structural-gap, rigid+scale alignment, elevation stats). Bounded structural claims; **must NOT be retro-upgraded** by any cook.
- **New cooked-map campaign** — a future effort under `artifacts/carla_map_cook/<run_id>/`; does not exist yet; adds a perception-ready cooked map only after B1–B4 + approval.
- **Reference-map role** — Grid0821/Grid0828 = evaluation reference, not production input; mislabeled-file disambiguation is P5.
- **Non-upgradable claims** — any prior runtime-XODR perception result cannot be relabeled "cooked custom perception map"; structural-gap metrics stand as-is at their committed SHA.

## 4. What went right (governance held)

HEAD==origin; canonical lock/sync/ledger consistent; no live writer; P5 correctly self-blocked and mutated nothing; P3 genuinely added `agent_sync.yaml`+ledger+lock (real progress vs the DV04 pre-P3 state where both were absent).

## Final status block

```
CLAUDE ARCHITECTURE VERDICT: REQUIRES_BASE_CORRECTION   [re-verified 2026-07-31 @ d4b0fe14]
  (blocks: BLOCKED_TOOLCHAIN [cook path, B4] + missing authoritative inputs [B2 CRITICAL, B3]; CODEX 5.5 NOT authorized)
  (CLEARED since first run: FAIL_HOOK_GOVERNANCE — B1 closed, P2/FCH01 PASS, GOV-HOOK-001 RESOLVED)

REPOSITORY:            github.com/lemoniadowyjohn/carla-control-suite.git
WORKTREE:              C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
BRANCH:                integration/governed-map-quality-20260729
SHA:                   d4b0fe14b51a714434a77c798d80e5f847eba748  (== origin; 0/0)  [first run was 5eddcc54]
CURRENT ARCHITECTURE:  A_RUNTIME_XODR_ONLY
TARGET ARCHITECTURE:   E_COOKED_LOADABLE_CUSTOM_MAP  (Track A; not yet actionable)

CARLA BRANCH:          0.9.16 (UE4.26 line, carla-simulator/carla)
CARLA COMMIT:          UNKNOWN — must-resolve (packaged build; source not pinned)
UNREAL VERSION:        UE4.26
UNREAL COMMIT:         UNKNOWN — must-resolve
BUILD WORKFLOW:        make (Track A); Linux+Docker source build for cook; UE5/CMake DISABLED

AUTHORITATIVE XODR:        UNKNOWN — must-resolve (B2; settings.INPUT_XODR is a computed path)
AUTHORITATIVE VISUAL INPUT: ABSENT — must-resolve (B3; 0 tracked FBX)
VISIBLE ROAD SOURCE:       CARLA runtime XODR extrusion (load_world); target = decide (recommend CARLA_GENERATED_ROAD)
OSM2WORLD ROLE:            supplementary, referenced-but-source-absent, NOT integrated
BLENDER ROLE:              NONE (absent)
TILING:                    target LEGACY_CARLA_LARGE_MAP_TILES (not World Partition); tile-size experiment deferred
COORDINATE CONTRACT:       WGS84→projCRS(UNKNOWN)→OpenDRIVE m→FBX→UE cm(LH,X-fwd,Y-right,Z-up)→CARLA
VERTICAL CONTRACT:         UNKNOWN — must-resolve (flat vs XODR-elevated vs DEM)

SEMANTIC STRATEGY:         CARLA UE4 tagger (deferred to cook)
COLLISION STRATEGY:        per-semantic-class (deferred to cook)
NAVIGATION STRATEGY:       Recast pedestrian nav after geometry stable (deferred)
TRAFFIC CONTROL STRATEGY:  XODR signals → CARLA actors (must-resolve; records-only today)
SESSION OWNER:            ultimate_pipeline/carla_tools/session.py (+ map_identity_guard, sensor_registry)
SENSOR CONTRACT:          use_K_undistortion=T, ignore_K=T, ignore_D=T, ctv_inverted=F, vtl_inverted=T  (CLARIFY contradiction)

UNREAL PROMPT READY:      NO — parameterized (AG05/UNREAL_COOKING_PARAMETERS.md), not authorized
CODEX 5.5 AUTHORIZED:     NO
BLOCKERS:                 [CLOSED] B1 P2-hook-governance · OPEN: B2 authoritative-XODR (CRITICAL) ·
                         B3 FBX/visible-road (HIGH) · B4 cook-toolchain-on-host (HIGH) ·
                         B5 osm/tiling/perception source-absent (MED) · B6 P1/P5 evidence untracked (LOW)
```

*Stopping at the verdict. P5, Unreal cooking, and CARLA execution are NOT started (read-only gate).*
