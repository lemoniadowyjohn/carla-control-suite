# carla-control-suite

An automated OSM-to-OpenDRIVE map-generation pipeline for CARLA, built to support a thesis studying
the domain gap between automatically generated maps and manually authored ones. Given an OSM extract,
`ultimate_pipeline` runs sanitization, topology repair, enrichment (lanes, elevation, crosswalks,
buildings), tiling, and validation to produce a CARLA-loadable `.xodr` map, plus a set of quality
gates and domain-gap/perception analysis tools used to evaluate the result.

## Canonical entrypoints

```
python -m ultimate_pipeline.cli doctor          # environment/config sanity check
python -m ultimate_pipeline.cli exp list         # list available experiments
python -m ultimate_pipeline.cli exp run <id> --config <path>
python -m ultimate_pipeline.cli test smoke       # fast smoke test
python -m ultimate_pipeline.run_pipeline         # run the full generation pipeline
```

`ultimate_pipeline/cli.py` is the single supported CLI (`up` in its own `--help` text); other
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
