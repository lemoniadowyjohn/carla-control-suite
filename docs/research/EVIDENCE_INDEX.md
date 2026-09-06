# Evidence Index

- Baseline packet: `reports/repo_health/20260906T102621Z_BASELINE/`
- Thesis assembly: `reports/post_audit_hardening/C19_THESIS_ASSEMBLY/`
- RQ1 determinism fixtures/tests: `tests/fixtures/opendrive/` and `tests/unit/test_exp_osm_to_xodr_determinism_normalized.py`
- RQ2 local evidence: `reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/` and `reports/post_audit_hardening/C26*`
- RQ4 thesis/current evidence: `reports/post_audit_hardening/C18_GNN_LATENT_GAP/` and `reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/`
- Map identities: `docs/runtime/MAP_OF_RECORD.md` and `ultimate_pipeline/carla_tools/map_registry.py`
- Repository health implementation: `ultimate_pipeline/tools/repo_health.py`

Generated rows in `rq_tables.json` carry evidence and input SHA256 values. Missing or deferred rows
remain explicit rather than being converted into PASS.
