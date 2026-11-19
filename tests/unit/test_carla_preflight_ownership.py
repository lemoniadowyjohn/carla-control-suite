from ultimate_pipeline.tools import carla_preflight as preflight


def test_force_restart_fails_closed_without_owned_process_handle(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(preflight, "_tcp_probe", lambda *a, **k: calls.append("tcp") or True)
    monkeypatch.setattr(preflight, "_kill_carla_windows", lambda: calls.append("kill") or {})
    monkeypatch.setattr(preflight, "_start_carla_server_windows", lambda *a, **k: calls.append("start") or {})
    monkeypatch.setattr(preflight, "_carla_api_probe", lambda *a, **k: calls.append("api") or {})

    result = preflight.run_preflight(force_restart=True, out_dir=str(tmp_path))

    assert result["ok"] is False
    assert result["error"] == "force_restart_refused_without_owned_process_handle"
    assert result["kill"] == {
        "attempted": False,
        "killed": False,
        "error": "image_wide_termination_disabled_without_owned_process_handle",
    }
    assert calls == ["tcp", "tcp"]
    assert (tmp_path / "carla_reachability.json").is_file()


def test_legacy_image_wide_kill_helper_is_inert(monkeypatch):
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("process termination is forbidden")),
    )

    result = preflight._kill_carla_windows()

    assert result["attempted"] is False
    assert result["killed"] is False
    assert "disabled" in result["error"]
