# 06 — FBX Reuse Decision

**STATUS: PENDING** — decided by Claude (§11.2) after **C44V01**.
Return exactly one: `REUSE_EXISTING_FBX` · `REUSE_EXISTING_FBX_AFTER_DECLARED_TRANSFORM` ·
`REGENERATE_FBX_FROM_AUTHORITATIVE_OSM` · `REGENERATE_OSM2WORLD_AND_FBX` · `BLOCKED_NO_TRUSTWORTHY_VISUAL_SOURCE`.
Reuse is allowed ONLY when: source OSM hash known · source bbox matches · projection known · origin known ·
units+axes known · alignment tests pass · semantic inventory adequate · geometry nonempty · no stale-output ambiguity.
**If the existing FBX was generated from a different OSM hash than the new authoritative XODR → regenerate.**
Base fact (AG07/B3): 0 tracked FBX on base — so any reusable FBX must come from a donor worktree via DSV01, by hash.
