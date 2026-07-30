# BC03 — agent_sync.yaml

- **Generated from the schema** (`AgentSyncContract().save("agent_sync.yaml")`), guaranteeing schema-validity —
  not hand-authored.
- **Loads + validates clean:** `load_agent_sync("agent_sync.yaml")` returns a valid `AgentSyncContract`;
  `validate_agent_sync(...)` → `valid: True`, `errors: []`, `warnings: []`.
- **Canonical lock binding:** `lock_policy.lock_file == ".agent_locks/writer.lock"` (asserted in test + at generation).
- **Sensor-rig directions (verified round-trip):** `use_K_undistortion=True`, `ignore_K=True`, `ignore_D=True`,
  `ctv_inverted=False` (cTv used directly), `vtl_inverted=True` (LiDAR inverted for CARLA).
- **Fixed bbox** (DO NOT CHANGE): lat [48.74935649548228, 48.77444431571603], lon [11.422268084715878, 11.47882091528412].
- **Determinism:** min_runs=5, preferred=10; signature fields incl. `xodr_sha256`, `tile_count`, `road_count`, `junction_count`.
- **Entrypoint discipline** is enforced by the loader/CLI (`python -m ultimate_pipeline.cli`; forbidden `config.settings`).

Verification test: `tests/unit/test_agent_sync_contract.py::test_repo_agent_sync_yaml_exists_loads_and_is_canonical` PASSED.
