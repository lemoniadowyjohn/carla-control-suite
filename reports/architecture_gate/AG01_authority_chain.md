# AG01 — Authority Chain Verification

**Gate:** P4 Fresh Independent Architecture Gate · **Mode:** read-only · **Session:** fresh Claude Opus 4.8 (≠ P0 drafting session)
**Verified live** on 2026-07-30 against the working tree; every row below is backed by a command, SHA, or file inspection.

## 1. Repository / worktree / branch / SHA

| Field | Value | Source |
|---|---|---|
| Repository (origin) | `github.com/lemoniadowyjohn/carla-control-suite.git` | DV04 handoff; `git remote` lineage |
| Worktree | `C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main` | `git rev-parse --show-toplevel` |
| Branch | `integration/governed-map-quality-20260729` | `git rev-parse --abbrev-ref HEAD` |
| HEAD SHA | `5eddcc543e6cd3b51b78e94f3586dc2c152e9c80` | `git rev-parse HEAD` |
| `origin/…` SHA | `5eddcc543e6cd3b51b78e94f3586dc2c152e9c80` | `git rev-parse origin/…` |
| Local == Remote | **YES** (0 ahead / 0 behind) | `git status -sb` |
| Tracked tree | clean (untracked non-P3 dirs + gitignored live lock only) | `git status --short` |

**Authority-chain SHA integrity: PASS.** HEAD equals the pushed tip; no divergence. Input reports may be trusted *as to SHA*, but each is still checked against source below (they are not trusted merely for existing).

## 2. Governance artifacts consistency

| Artifact | State | Evidence |
|---|---|---|
| `agent_sync.yaml` | Present at repo root; `version: 1`; `lock_policy.lock_file = .agent_locks/writer.lock`; bbox + sensor rig + determinism signature pinned | read live |
| `AGENT_TASK_LEDGER.md` | Present; wired; canonical lock referenced; single-writer rules stated | read live |
| Canonical lock code | `ultimate_pipeline/contracts/writer_lock.py` (schema `agent-writer-lock/v1`, `CANONICAL_LOCK_PATH=.agent_locks/writer.lock`) — **tracked** | BC02 + `git ls-files` |
| Live lock file | `.agent_locks/writer.lock` — **gitignored** (runtime/ephemeral); policy tracked at `.agent_locks/README.md` | BC02 (decision "A") |
| Live writer present? | **NO** — P3 lock (`P3-BASE-CLOSURE`) released at BC06; no active lease | BC06 |
| Lock tests | 16 passed (`test_writer_lock.py` + `test_agent_sync_contract.py`) | BC02/BC05 |

**Consistency check:** `agent_sync.yaml.lock_policy.lock_file` == ledger's canonical lock path == `writer_lock.CANONICAL_LOCK_PATH` == `.agent_locks/writer.lock`. **CONSISTENT.**

## 3. Sensor / dataset identity contract (pinned in `agent_sync.yaml`)

- `bbox`: lat `48.74936–48.77444`, lon `11.42227–11.47882` → **Ingolstadt** extent.
- `sensor_rig`: `use_K_undistortion=true`, `ignore_K=true`, `ignore_D=true`, `ctv_inverted=false`, `vtl_inverted=true`, `rig_verification_required=true`, `screenshot_required=true`.
  - **2026-08-15 D2 update:** the apparent `use_K_undistortion` / `ignore_K,D` tension is resolved as CARLA ideal-pinhole semantics: ignore raw `K/D`, derive simulator intrinsics from `K_undistortion` + `image_size`, use `cTv` directly, invert `vTl`. Evidence: `reports/post_audit_hardening/D2_SENSOR_CALIBRATION_SEMANTICS.md`.
- `determinism.required_signature_fields`: `xodr_sha256`, `tile_metadata_sha256`, `tile_count`, `road_count`, `junction_count` — this is the **dataset identity contract**, enforced at runtime by `carla_tools/map_identity_guard.py`.

## 4. Authority-chain verdict

**AUTHORITY_CHAIN = CONSISTENT (SHA-synced, lock/sync/ledger aligned, no live writer).**
This is a *necessary* precondition for the gate; it is **not** sufficient — the prerequisite prompt statuses (AG-adjacent, see AG07) and the architecture-input completeness (AG02–AG05) are evaluated separately and are where the gate actually blocks.
