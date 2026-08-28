import ultimate_pipeline.tools.run_perception_safe as m


def test_default_calib_exists() -> None:
    # _default_calib_path() is the resolver _resolve_calib_path() actually calls at
    # runtime; the module-level _DEFAULT_CALIB_PATH = "calib_data.json" constant this
    # test used to check is a stale, unused duplicate (missing the
    # "ultimate_pipeline/sensors/" prefix, never referenced by any real code path).
    p = m._default_calib_path()
    assert p.exists(), f"Default calib not found: {p}"
