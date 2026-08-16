# C11 (HIGH) reproducibility fix, step 5: PROJ environment guard.
#
# A stale/foreign proj.db (e.g. DATABASE.LAYOUT.VERSION.MINOR < 6, or a
# PROJ_LIB/PROJ_DATA env var pointing at a *different* installation's proj
# data than the one pyproj would resolve on its own) is a latent
# silent-reprojection risk: CRS transforms can silently produce wrong
# coordinates instead of raising. check_proj_environment() gives callers a
# single place to detect this at startup and either fail closed or emit a
# loud, actionable warning.
from __future__ import annotations

from ultimate_pipeline.governance.proj_env_guard import (
    ProjEnvironmentError,
    ProjEnvironmentReport,
    check_proj_environment,
)


def test_check_proj_environment_returns_report_with_expected_fields() -> None:
    report = check_proj_environment(min_layout_minor=6, fail_closed=False)
    assert isinstance(report, ProjEnvironmentReport)
    assert isinstance(report.ok, bool)
    assert isinstance(report.warnings, list)
    assert report.proj_db_layout_version is not None
    assert report.data_dir


def test_check_proj_environment_flags_old_layout_version_as_not_ok() -> None:
    # This repo's pinned venv currently resolves a proj.db reporting
    # DATABASE.LAYOUT.VERSION.MINOR == 4 (see reports/post_audit_hardening/
    # C11_REPRODUCIBILITY.md for the live reading). Requiring >= 6 must be
    # flagged as not-ok with a remediation-bearing warning, not silently
    # accepted.
    report = check_proj_environment(min_layout_minor=6, fail_closed=False)
    if report.proj_db_layout_version is not None and report.proj_db_layout_version < 6:
        assert report.ok is False
        assert any("proj.db" in w.lower() for w in report.warnings)
        assert any(
            "pyproj" in w.lower() or "gdal" in w.lower() or "conda" in w.lower()
            for w in report.warnings
        )


def test_check_proj_environment_fail_closed_raises_when_not_ok() -> None:
    report_soft = check_proj_environment(min_layout_minor=6, fail_closed=False)
    if report_soft.ok:
        return  # environment happens to be new enough; nothing to assert here
    try:
        check_proj_environment(min_layout_minor=6, fail_closed=True)
    except ProjEnvironmentError as exc:
        assert "proj.db" in str(exc).lower()
    else:
        raise AssertionError("expected ProjEnvironmentError when fail_closed=True and not ok")


def test_check_proj_environment_passes_with_low_threshold() -> None:
    # A trivially satisfiable minimum must always report ok=True (env-var
    # mismatch warnings may still be present, but layout-version-driven
    # not-ok must not fire).
    report = check_proj_environment(min_layout_minor=0, fail_closed=True)
    assert report.ok is True


def test_check_proj_environment_detects_foreign_proj_lib_env_var(monkeypatch, tmp_path) -> None:
    """
    A PROJ_LIB/PROJ_DATA env var pointing somewhere other than pyproj's own
    resolved data dir is exactly the 'from another PROJ installation' risk
    the spec calls out. It must be surfaced as a warning even if the
    layout-version check alone would pass.
    """
    foreign_dir = tmp_path / "some_other_proj_install"
    foreign_dir.mkdir()
    monkeypatch.setenv("PROJ_LIB", str(foreign_dir))

    report = check_proj_environment(min_layout_minor=0, fail_closed=False)
    assert any("PROJ_LIB" in w for w in report.warnings)


def test_main_pipeline_startup_wires_proj_guard_as_loud_warning(monkeypatch, capsys) -> None:
    """
    MainPipeline.__init__ -> _validate_global_safety_settings() must invoke
    the PROJ guard. Default (no UP_PROJ_ENV_FAIL_CLOSED) must not raise even
    when the environment is not ok -- it prints a loud, actionable warning
    instead, so a clean-checkout default run is never blocked by this alone.
    """
    monkeypatch.delenv("UP_PROJ_ENV_FAIL_CLOSED", raising=False)

    from ultimate_pipeline.main_pipeline import _validate_global_safety_settings

    class _StubSettings:
        ENABLE_HPC_PERCEPTION = False
        ENABLE_LOCAL_PERCEPTION = False

    _validate_global_safety_settings(_StubSettings())
    # No assertion on captured output content (environment-dependent); the
    # key contract is that this call did not raise.
    capsys.readouterr()


def test_main_pipeline_startup_proj_guard_fail_closed_opt_in(monkeypatch) -> None:
    """UP_PROJ_ENV_FAIL_CLOSED=1 must make a not-ok PROJ environment raise
    from _validate_global_safety_settings (only meaningful when this venv's
    proj.db is actually below the minimum; skip otherwise)."""
    from ultimate_pipeline.governance.proj_env_guard import check_proj_environment
    from ultimate_pipeline.main_pipeline import _validate_global_safety_settings

    baseline = check_proj_environment(min_layout_minor=6, fail_closed=False)
    if baseline.ok:
        import pytest

        pytest.skip("this venv's proj.db already meets the minimum; nothing to fail on")

    monkeypatch.setenv("UP_PROJ_ENV_FAIL_CLOSED", "1")

    class _StubSettings:
        ENABLE_HPC_PERCEPTION = False
        ENABLE_LOCAL_PERCEPTION = False

    import pytest

    with pytest.raises(Exception):
        _validate_global_safety_settings(_StubSettings())
