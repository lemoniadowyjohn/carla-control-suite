# Repository Health

`up health` and `python -m ultimate_pipeline.tools.repo_health` emit `repo_health.json` and
`REPO_HEALTH.md`. The release vocabulary is `PASS`, `FAIL`, `INCOMPLETE`, `NOT_RUN`, and
`BLOCKED_EXTERNAL`.

Missing evidence is not a pass. In particular, absent `qa_stage_reports/` evidence is `NOT_RUN` or
`INCOMPLETE`, and a clean offline suite does not imply runtime certification. The packet records
branch, HEAD, dirty state, Python/package metadata, dependency integrity, tests, governance,
research-contract status, map identity, evidence completeness, and runtime status.
