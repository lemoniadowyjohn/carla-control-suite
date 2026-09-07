# CARLA Control Suite

An automated OSM-to-OpenDRIVE map-generation pipeline for CARLA, built to support a thesis studying
the domain gap between automatically generated maps and manually authored ones. Given an OSM extract,
`ultimate_pipeline` runs sanitization, topology repair, enrichment (lanes, elevation, crosswalks,
buildings), tiling, and validation to produce a CARLA-loadable `.xodr` map, plus a set of quality
gates and domain-gap/perception analysis tools used to evaluate the result.

This is a research repository for reproducible OSM to OpenDRIVE generation and controlled CARLA
domain-gap experiments. It is not a claim that every thesis question is complete.

- CARLA target: `0.9.16`.
- Authoritative lineage: `fix/post-audit-phase-e-junctions-roundabouts-20260803`.
- Stabilization branch: `stabilize/research-release-20260905`.
- Canonical command: `up` (or `python -m ultimate_pipeline.cli`).
- Map of record: `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr`.
- Manual reference: `campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr` — the manually modeled CARLA map that is the RQ2 structural-gap baseline (verify via `verify_pinned_map('manual_grid0828')`).
- CI: the offline gates are defined in `.github/workflows/tests.yml` (six jobs: offline tests, wheel smoke, governance, RQ contract, provenance, repository health). Verified green on `review/claude-independent-audit-20260906` @ `2e020d9b` (run `34044481507`, `pull_request`-triggered, all 6 jobs pass, completed 2026-09-06T16:08:15Z) — re-verify against the actual current HEAD before citing this as current, since CI status is a point-in-time fact, not a durable claim. `.github/workflows/carla-runtime.yml` (live CARLA runtime evidence) exists but cannot currently execute: zero self-hosted runners are registered for this repo, and its health-packet step has a known fail-open defect (`MAP_QUALITY_GAP_REGISTER.json` GAP-031) that must be fixed before its output can be trusted even once a runner exists.
- Health: offline gates are executable; live CARLA verification is `NOT_RUN` unless a self-hosted runtime workflow is executed.
- Thesis relationship: `submission/` is frozen evidence; current work is measured against the immutable RQ contract.

RQ1 is authoritative for structural determinism and bounded for timestamp-normalized bytes. RQ2 is bounded. RQ4 is authoritative with explicit thesis-baseline caveats. RQ3 and RQ5 remain deferred and are not inferred from Town10HD or unlabeled shift metrics.

## Canonical entrypoints

```
python -m ultimate_pipeline.cli doctor          # environment/config sanity check
python -m ultimate_pipeline.cli exp list         # list available experiments
python -m ultimate_pipeline.cli exp run <id> --config <path>
python -m ultimate_pipeline.cli test smoke       # fast smoke test
up pipeline run                                  # run the full generation pipeline
up health                                        # emit repo_health.json and REPO_HEALTH.md
up research status                               # show thesis-aligned RQ statuses
```

`ultimate_pipeline/cli.py` is the single supported CLI; other
top-level scripts under `scripts/` and `tools/` are one-off diagnostics, audits, and evidence-export
utilities for specific research questions (see their docstrings/`--help`).

## Map of record

The pipeline's current canonical output is tracked by content hash (not by filename) in
`ultimate_pipeline/carla_tools/map_registry.py::PINNED_MAP_REGISTRY`. Verify what's currently pinned:

```
python -c "from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map; \
           print(verify_pinned_map('auto_map_of_record'))"
```

To regenerate it from scratch (requires a clean git worktree):

```
python scripts/regen_map_of_record.py
```

## Reproducing / running the test suite

```
pip install -r requirements.txt
pytest
```

The reproducibility entrypoint is [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md). Run
`up doctor` before CARLA work and `up health` after the offline gates.

`pytest.ini` scopes collection to `ultimate_pipeline/tests/`, `tests/`, and several package-local
`tests/` directories — running bare `pytest` from the repo root picks up all of them.

## Research questions and evidence status

This repo's evidence-export tooling (`tools/export_thesis_tables.py`, cross-checked by
`ultimate_pipeline/tools/audit_thesis_topic_contract.py` and
`tools/validate_thesis_claim_provenance.py`) tracks five research questions, matching
`submission/thesis_source/Chapter1/chap1.tex`:

| RQ | Topic | Status |
|----|-------|--------|
| RQ1 | Determinism (byte-level vs. structural) | AUTHORITATIVE |
| RQ2 | Structural domain gap (auto vs. manual map) | BOUNDED |
| RQ3 | Perceptual domain gap (paired CARLA capture) | DEFERRED — blocked on a live CARLA server |
| RQ4 | Structural variability / latent representation (GNN) | AUTHORITATIVE (with caveats) |
| RQ5 | Generalization and transfer (sim + real-world) | DEFERRED — blocked on RQ3's capture pipeline, plus (5b) no real-world dataset |

Regenerate this table directly against current evidence:

```
python tools/export_thesis_tables.py --out reports/post_audit_hardening/C19_THESIS_ASSEMBLY
python -m ultimate_pipeline.tools.audit_thesis_topic_contract --out reports/post_audit_hardening/C19_THESIS_ASSEMBLY/contract_audit.json
```

See `docs/research/THESIS_TO_CURRENT_PROGRESS.md` for what's changed since the submitted thesis.

## Repository layout

- `ultimate_pipeline/` — the pipeline itself: `pipeline_stages/`, `enrichment/`, `quality/`,
  `topology/`, `domain_gap/`, `carla_tools/`, `experiments/`.
- `opendrive_geometry/`, `phase_q/` — supporting packages (geometry primitives; governance/payload
  layer), packaged alongside `ultimate_pipeline` (see `pyproject.toml`).
- `tests/`, `ultimate_pipeline/tests/`, and package-local `tests/` directories — the test suite.
- `reports/post_audit_hardening/` — dated evidence artifacts and audit reports from the post-thesis
  hardening work.
- `submission/` — the frozen, archived thesis-submission deliverable; not imported by production code
  and excluded from test collection.
