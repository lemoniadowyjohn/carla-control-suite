# Independent Review Request — RQ3->RQ5 Handoff Repair (Updated for final SHA)

- Worktree: `E:\wt\repair-map-realism-p0-837a8504`
- Implementation SHA reviewed: `9e777a270f91299bd20efcc879919029e2956e45` (short: `9e777a27`)
- Receipt SHA (this doc): will be assigned at separate commitment; NOT self-referenced with `9e777a27`
- Branch: `repair/map-realism-p0-837a8504`
- Author / writer: single engineer (`dba5aabe` → `9e777a27` chain)
- Independent review status: **INDEPENDENT_REVIEW_NOT_RUN**
- Frozen protocol authority: `configs/rq3_protocol_freeze_v1.json` (SHA-256 `5aa8ae2...`) — present, unedited, tracked at `9e777a27`

## Verified artifacts at `9e777a27`
- Strict CLI dispatch (`record_route_fixed.py`): `main()` routes `--strict-rq3` to `run_strict_capture_entrypoint`; no legacy fallback; `__main__` after strict definitions.
- Synthetic-to-authoritative gate (`rq3_evidence_gate.py`): evidence states separated (`structural_test_valid`, `synthetic_fixture_valid`, `real_capture_complete`, `dataset_admitted`, `experimental_evidence_authoritative`); claim never promoted without live-capture provenance + independent review + verified artifacts.
- Manifest promotion (`experiment_map_pair_authority.py`): derived `pair_valid` from evidence predicates (not caller flag); strict validator applied; claim downgraded when invalid.
- Artifact byte verification (`rq3_evidence_gate.verify_artifact_set`): SHA-256 of actual file contents; path traversal blocked; stale session / uncommitted staging / duplicate identity / missing modality / modified after manifest all rejected.
- Frozen protocol tracked unedited (`configs/rq3_protocol_freeze_v1.json`).
- Reproducible environment: `C:\temp\py312_venv`; Python 3.12.2; pytest 9.1.1; `import carla` PASS.

## Evidence receipts bound to `9e777a27`
- `RQ3_EVIDENCE_RECEIPT_20261022_9e777a27.json`
- `RQ3_HANDOFF_PARTIAL_EXACT_BLOCKERS.md`
- `RQ3_PATCH_MANIFEST.json` (updated)

## Blockers preserved (not masked)
- `RQ3_PAIRED_DATASET_NOT_ADMITTED`: no paired runtime capture.
- `INDEPENDENT_REVIEW_NOT_RUN`: only one engineer executed.
- `CARLA_SERVER_STARTUP`: blocked (shader + ALargeMapManager AV + storage gate).
- Some pre-existing unrelated contract failures remain in wider regression suite (not masked by this fix).

## Request
Request independent Codex reviewer to execute:
1. Inspect committed tree at SHA `9e777a27` (`git show 9e777a27 --stat`).
2. Reproduce strict CLI (`python -m pytest ...`) with the exact venv interpreter (`C:\temp\py312_venv\Scripts\python.exe`).
3. Verify synthetic fixtures stay `SYNTHETIC_TEST_ONLY`; verify no promotion path exists through helper/manifest/CLI/adapter without verified artifacts + `APPROVED` independent review + live-capture provenance.
4. Confirm frozen protocol bytes unchanged (`sha256sum configs/rq3_protocol_freeze_v1.json`).
5. Confirm receipt SHA `9e777a27` is the tested implementation, not recycled from an earlier commit.

Do NOT merge to production until (a) independent review completed, (b) dataset admission verified from live paired capture, (c) server startup resolved.
