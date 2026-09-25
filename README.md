# CARLA Control Suite

An automated OSM-to-OpenDRIVE map-generation pipeline for CARLA, built to support a thesis studying
the domain gap between automatically generated maps and manually authored ones. Given an OSM extract,
`ultimate_pipeline` runs sanitization, topology repair, enrichment (lanes, elevation, crosswalks,
buildings), tiling, and validation to produce a CARLA-loadable `.xodr` map, plus a set of quality
gates and domain-gap/perception analysis tools used to evaluate the result.

This is a research repository for reproducible OSM to OpenDRIVE generation and controlled CARLA
domain-gap experiments. It is not a claim that every thesis question is complete.

- CARLA target: `0.9.16`.
- Canonical engineering branch: `integration/production-large-map-20260918`.
- GitHub default branch: currently `main`, which is historical/obsolete for active engineering work; default-branch migration remains a separate governance task.
- Canonical command: `up` (or `python -m ultimate_pipeline.cli`).
- Map of record: resolve `auto_map_of_record` through `verify_pinned_map(...)`; the current verified pin is `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr` (SHA256 `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`).
- Manual reference: `campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr` — the manually modeled CARLA map used as the RQ2 structural-gap baseline (verify via `verify_pinned_map('manual_grid0828')`).
- CI: the offline gates are defined in `.github/workflows/tests.yml` (offline tests, wheel smoke, governance, RQ contract, provenance, repository health). The 2026-09-24 closure evidence records six-job GitHub Actions success on `52bf6c27`; the production tip later recorded a post-merge full suite of **6264 passed, 6 skipped, 0 failed**. A documentation-only commit after a green run does not by itself create a new runtime/CI claim.
- Health: repository-health PASS is an offline result unless the separate self-hosted `.github/workflows/carla-runtime.yml` workflow has actually executed successfully.
- Thesis relationship: `submission/` is frozen evidence; current work is measured against the immutable RQ contract.

RQ1 remains authoritative for structural repeatability and bounded for byte-level/normalized determinism outside the proven scope. RQ2 is bounded. RQ4's leak-free five-seed extension is now supported by passing pre-training and post-hoc leakage audits (GAP-010 closed). RQ3 remains deferred until paired manual/automatic CARLA capture is executed, and RQ5 remains downstream of that runtime evidence.

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
| RQ4 | Structural variability / latent representation (GNN) | AUTHORITATIVE current extension — leak-free 5-seed retrain complete; pre-training and post-hoc leakage audits PASS |
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
