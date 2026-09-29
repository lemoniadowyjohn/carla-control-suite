# B2 — Test Suite Platform Assumption Audit

- Date: 2026-09-24
- Mode: read-only audit + one bounded fix
- Scope: every pytest-discoverable `test_*.py` under `tests/` and `ultimate_pipeline/**/tests/` (416 files), plus both `conftest.py` files

## Objective

A clean, offline Linux CI worker (no Blender, no CARLA, no Unreal, no Java,
no OSM2World, no SUMO, no GPU, no network, no developer home/drive paths)
must be able to run the intended **unit** suite.

## Method

Full pass over the suite for: real Blender (`bpy`, blender subprocesses),
Java, OSM2World, CARLA/Unreal (live `carla.Client`, exe launches), network
services (requests/socket/http), local-drive and user-home paths, GPU APIs,
and external executables (`netconvert`, `osmosis`, `ogr2ogr`, etc.), plus a
classification of every hit as TRUE_UNIT / INTEGRATION / SYSTEM /
ENV_DEPENDENT.

## Environment-dependent tests detected

| file:line | dependency | classification | intentional? |
| --- | --- | --- | --- |
| `conftest.py:8` | `import __editable___ultimate_pipeline_0_1_0_finder` (pip editable-install artifact) | SYSTEM (collection-level) | NO — the one accidental dep |
| `tests/quality/test_ingolstadt_coordinate_verification.py:22-66` | git-committed ~81 MB XODR candidates + `coordinate_tests.json` | INTEGRATION (repo golden data) | yes |
| `tests/unit/test_stage_d0.py`, `tests/test_stage_i_integrity.py`, `tests/unit/test_pack_thesis_run.py`, `tests/unit/test_determinism_and_stage_j.py` | git-committed `reports/...`, `campaigns/...` artifacts | INTEGRATION | yes |
| `tests/test_r13_c0r_tag_freeze.py` | `git` binary on PATH (throwaway tmp repos) | INTEGRATION | yes |
| `tests/unit/test_sumo_repair_frame_preservation.py:99` | real `netconvert` | INTEGRATION | yes — already `@pytest.mark.skipif(not _sumo_available)` gated (project precedent) |
| `tests/unit/test_train_launcher_synthetic_dry_run.py`, `test_train_launcher_any_255.py`, `ultimate_pipeline/tests/unit/test_latent_gap_runner.py` | `torch` / `torchvision` / `torch_geometric` (pip deps, CPU only) | INTEGRATION (in-process offline) | yes |
| `tests/carla_tools/test_session.py:11-13` | TCP connect to `localhost:29999` expecting failure | INTEGRATION (loopback-negative) | yes |
| `ultimate_pipeline/tests/unit/test_carla_preflight_tcp_probe.py:24-36` | self-contained loopback bind/listen/close | INTEGRATION (loopback) | yes |
| `tests/unit/test_writer_lock_adversarial.py` | local multiprocessing spawn workers | INTEGRATION (local) | yes — `@pytest.mark.slow` |

All other CARLA/Blender/OSM2World/SUMO/RoadRunner/LLM/Ollama/netconvert
touchpoints already use the project's established fakes (module flags like
`CARLA_AVAILABLE`, `sys.modules` fakes, duck-typed stand-ins, `tmp_path`
fake binaries, mocked `subprocess.run`). No `torch.cuda`/`device="cuda"`,
no unresisted `requests`, no `C:\Users\admin` or `PyCharmProjects` path is
required by any test (one test actively asserts production defaults contain
none: `tests/unit/test_a1_a2_path_and_frame_resolution.py:141`).

## Verdict

The intended unit suite runs on a clean offline Linux worker **once** the
following are true:

1. repo is cloned fully (no shallow/sparse — golden-data integration tests
   need the committed large files), and pip deps are installed;
2. the root `conftest.py` does not hard-require the editable-install finder.

Item 2 was the only accidental environment dependence found and is fixed
below.

## Fix performed (bounded, no fakes needed elsewhere)

`conftest.py`: the `import __editable___ultimate_pipeline_0_1_0_finder`
(site-packages artifact of `pip install -e .`) broke **collection of every
test** on a worker that synchronized the tree without an editable install.
Wrapped in `try/except ModuleNotFoundError` with a `sys.path` bootstrap
fallback (the pattern already used by `ultimate_pipeline/tests/conftest.py`);
behavior on editable-installed machines is unchanged.

## Fixes intentionally NOT made

Genuine INTEGRATION / SYSTEM tests keep their real boundaries (they are the
point) and are now environmentally documented here and by their existing
skip gates (`_sumo_available`, `@pytest.mark.slow`). No tests were broadly
skipped.

## Test results after the fix

- `tests/unit/test_sumo_repair_frame_preservation.py` + `test_agent_sync_contract.py`: 8 passed
- fallback path verified: with the editable finder blocked, `import ultimate_pipeline` resolves from the repo tree
- WriterLock suite (B1) unaffected

## Required environment for the INTEGRATION / SYSTEM tests

- full git checkout (committed large artifacts under `reports/` and `campaigns/`)
- `git` on PATH
- (optional) SUMO `netconvert` for the single gated test
- (optional) torch stack for the three ML entrypoint tests
- nothing needs Blender/CARLA/Unreal/Java/OSM2World/GPU/network