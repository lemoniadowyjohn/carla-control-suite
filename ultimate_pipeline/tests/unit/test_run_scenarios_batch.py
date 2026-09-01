# ultimate_pipeline/tools/run_scenarios_batch.py -- zero prior test
# coverage. Standalone CLI (not imported by the live pipeline; needs
# CARLA + ScenarioRunner to run meaningfully), but a real, unambiguous bug
# was found by direct grep, not speculation:
#
# _resolve_run_dir() called validate_thesis_run._resolve_real_run_dir(p)
# under a `# type: ignore[attr-defined]` comment -- that function does not
# exist anywhere in the codebase (confirmed via a repo-wide grep: the only
# match for "_resolve_real_run_dir" was this one call site) and never has
# (validate_thesis_run.py has no "resolve a run dir" concept at all -- it
# only validates artifacts within an already-resolved run_root). Every
# call raised AttributeError, caught by the surrounding try/except and
# silently discarded, always falling through to `return p` unchanged --
# so the documented "wrapper run dir" resolution feature never worked, a
# single time, for anyone. Fixed: the dead call and unused import are
# removed; _resolve_run_dir() is now honest about what it always actually
# did (pass the path through unchanged) instead of pretending to attempt
# real resolution logic that could never succeed.
from __future__ import annotations

from pathlib import Path

import pytest

from ultimate_pipeline.tools import run_scenarios_batch as rsb


def test_resolve_run_dir_returns_path_unchanged(tmp_path: Path):
    p = tmp_path / "some_run"
    p.mkdir()

    result = rsb._resolve_run_dir(p)

    assert result == p


def test_module_does_not_import_validate_thesis_run():
    # Regression guard for the dead cross-module attribute access: the
    # import existed solely to support the nonexistent
    # _resolve_real_run_dir() call.
    import ultimate_pipeline.tools.run_scenarios_batch as mod
    assert not hasattr(mod, "validate_thesis_run")


def test_expand_runs_literal_paths_preserved_in_order():
    result = rsb._expand_runs(["run_a", "run_b", "run_c"])
    assert result == [Path("run_a"), Path("run_b"), Path("run_c")]


def test_expand_runs_glob_expands_and_sorts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "run_02").mkdir()
    (tmp_path / "run_01").mkdir()
    (tmp_path / "run_10").mkdir()

    result = rsb._expand_runs(["run_*"])

    assert [p.name for p in result] == ["run_01", "run_02", "run_10"]


def test_expand_runs_mixed_literal_and_glob(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "glob_a").mkdir()

    result = rsb._expand_runs(["explicit_run", "glob_*"])

    assert Path("explicit_run") in result
    assert any(p.name == "glob_a" for p in result)


def test_scenario_name_from_xosc_uses_stem_by_default():
    name = rsb._scenario_name_from_xosc(Path("scenarios/my_scenario.xosc"), None)
    assert name == "my_scenario"


def test_scenario_name_from_xosc_override_wins():
    name = rsb._scenario_name_from_xosc(Path("scenarios/my_scenario.xosc"), "custom_name")
    assert name == "custom_name"


def test_write_json_creates_parent_dirs_and_content(tmp_path: Path):
    out = tmp_path / "nested" / "dir" / "status.json"

    rsb._write_json(out, {"ok": True, "reason": "dry_run"})

    assert out.is_file()
    content = out.read_text(encoding="utf-8")
    assert '"ok": true' in content
    assert '"reason": "dry_run"' in content
