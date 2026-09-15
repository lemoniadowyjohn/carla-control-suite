"""ultimate_pipeline/tools/run_perception_safe.py -- coverage for the Grid0821/Grid0828
known-unstable-map mitigation layer: _is_known_unstable_map, _apply_unstable_map_env_defaults,
and the pure downstream consumer _handle_outer_stream_gate.

Context: CARLA 0.9.16 has a documented, real engine crash on these two grid maps (see the
module's top docstring and GRID_PERCEPTION_RCA.md) --

  1. Sensor teardown can crash in ASensor::EndPlay even after stop() succeeds; mitigated by
     UP_SKIP_DESTROY=1, which is read by ultimate_pipeline/perception/record_route_fixed.py
     (and record_route.py) to skip explicit sensor.destroy() calls.
  2. The streaming port (2001) does not reliably come up via load_world() on these maps;
     mitigated by UP_SKIP_STREAM_CHECK=1, which round-trips into args.skip_stream_check
     (see main(), around the "Propagate UP_SKIP_STREAM_CHECK env var" comment) and gates
     _handle_outer_stream_gate plus the `stream_optional` computation.
  3. Map travel itself is risky; a separate code path (not covered here) hard-blocks
     load_world() into these maps unless --use-current-world is passed.

None of this had any regression coverage before this test file (grep across tests/ for
_is_known_unstable_map / _apply_unstable_map_env_defaults / KNOWN_UNSTABLE_MAPS returned zero
hits) despite existing specifically to guard against a known, real CARLA crash.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

from ultimate_pipeline.tools.run_perception_safe import (
    KNOWN_UNSTABLE_MAPS,
    _apply_unstable_map_env_defaults,
    _handle_outer_stream_gate,
    _is_known_unstable_map,
)


# ---------------------------------------------------------------------------
# KNOWN_UNSTABLE_MAPS -- sanity on the registry itself
# ---------------------------------------------------------------------------


def test_known_unstable_maps_contains_exactly_the_two_grid_maps():
    assert KNOWN_UNSTABLE_MAPS == frozenset({"grid0821", "grid0828"})


# ---------------------------------------------------------------------------
# _is_known_unstable_map -- known-unstable names, case/prefix variants
# ---------------------------------------------------------------------------


def test_is_known_unstable_map_true_for_grid0828_canonical_case():
    assert _is_known_unstable_map("grid0828") is True


def test_is_known_unstable_map_true_for_grid0821_canonical_case():
    assert _is_known_unstable_map("grid0821") is True


def test_is_known_unstable_map_true_for_mixed_case_variant():
    assert _is_known_unstable_map("Grid0828") is True


def test_is_known_unstable_map_true_for_uppercase_variant():
    assert _is_known_unstable_map("GRID0828") is True


def test_is_known_unstable_map_true_for_mixed_case_grid0821():
    assert _is_known_unstable_map("Grid0821") is True


def test_is_known_unstable_map_true_for_cooked_map_path_prefix():
    # normalize_map_name strips "Carla/Maps/" style prefixes before comparison.
    assert _is_known_unstable_map("Carla/Maps/Grid0828") is True


def test_is_known_unstable_map_true_for_game_path_prefix():
    assert _is_known_unstable_map("/Game/Carla/Maps/Grid0821") is True


# ---------------------------------------------------------------------------
# _is_known_unstable_map -- known-stable names
# ---------------------------------------------------------------------------


def test_is_known_unstable_map_false_for_town_map():
    assert _is_known_unstable_map("Town10HD_Opt") is False


def test_is_known_unstable_map_false_for_another_town_map():
    assert _is_known_unstable_map("Town03") is False


def test_is_known_unstable_map_false_for_empty_string():
    assert _is_known_unstable_map("") is False


def test_is_known_unstable_map_false_for_none():
    assert _is_known_unstable_map(None) is False


def test_is_known_unstable_map_false_for_underscore_variant_not_normalized():
    # normalize_map_name only strips path prefixes and lowercases -- it does NOT
    # collapse underscores/spacing. "grid_0828" therefore stays "grid_0828" and is
    # NOT treated as unstable. This documents actual normalize_map_name behavior
    # (verified directly against ultimate_pipeline.carla_tools.map_registry).
    assert _is_known_unstable_map("grid_0828") is False


# ---------------------------------------------------------------------------
# _apply_unstable_map_env_defaults -- unstable map sets both env vars
# ---------------------------------------------------------------------------


def test_apply_env_defaults_unstable_map_sets_both_vars(monkeypatch):
    monkeypatch.delenv("UP_SKIP_DESTROY", raising=False)
    monkeypatch.delenv("UP_SKIP_STREAM_CHECK", raising=False)

    result = _apply_unstable_map_env_defaults("Grid0828")

    assert result is True
    assert os.environ.get("UP_SKIP_DESTROY") == "1"
    assert os.environ.get("UP_SKIP_STREAM_CHECK") == "1"


def test_apply_env_defaults_unstable_map_grid0821_sets_both_vars(monkeypatch):
    monkeypatch.delenv("UP_SKIP_DESTROY", raising=False)
    monkeypatch.delenv("UP_SKIP_STREAM_CHECK", raising=False)

    result = _apply_unstable_map_env_defaults("grid0821")

    assert result is True

    assert os.environ.get("UP_SKIP_DESTROY") == "1"
    assert os.environ.get("UP_SKIP_STREAM_CHECK") == "1"


def test_apply_env_defaults_stable_map_returns_false_and_touches_neither_var(monkeypatch):
    monkeypatch.delenv("UP_SKIP_DESTROY", raising=False)
    monkeypatch.delenv("UP_SKIP_STREAM_CHECK", raising=False)

    result = _apply_unstable_map_env_defaults("Town10HD_Opt")

    assert result is False

    assert "UP_SKIP_DESTROY" not in os.environ
    assert "UP_SKIP_STREAM_CHECK" not in os.environ


def test_apply_env_defaults_empty_town_returns_false(monkeypatch):
    monkeypatch.delenv("UP_SKIP_DESTROY", raising=False)
    monkeypatch.delenv("UP_SKIP_STREAM_CHECK", raising=False)

    assert _apply_unstable_map_env_defaults("") is False

    assert "UP_SKIP_DESTROY" not in os.environ
    assert "UP_SKIP_STREAM_CHECK" not in os.environ


# ---------------------------------------------------------------------------
# _apply_unstable_map_env_defaults -- override / escape-hatch behavior
# ---------------------------------------------------------------------------


def test_apply_env_defaults_honors_explicit_skip_stream_check_zero(monkeypatch):
    # Explicit escape hatch: a user who has confirmed the streaming port IS open
    # can force UP_SKIP_STREAM_CHECK=0 and the mitigation must not clobber it.
    monkeypatch.delenv("UP_SKIP_DESTROY", raising=False)
    monkeypatch.setenv("UP_SKIP_STREAM_CHECK", "0")

    result = _apply_unstable_map_env_defaults("Grid0828")

    assert result is True

    # UP_SKIP_DESTROY is still applied via setdefault (unrelated to the stream-check override).
    assert os.environ.get("UP_SKIP_DESTROY") == "1"
    # But the user's explicit "0" must be preserved, not overwritten to "1".
    assert os.environ.get("UP_SKIP_STREAM_CHECK") == "0"


def test_apply_env_defaults_honors_explicit_skip_stream_check_false_string(monkeypatch):
    monkeypatch.delenv("UP_SKIP_DESTROY", raising=False)
    monkeypatch.setenv("UP_SKIP_STREAM_CHECK", "false")

    _apply_unstable_map_env_defaults("Grid0828")


    assert os.environ.get("UP_SKIP_STREAM_CHECK") == "false"


def test_apply_env_defaults_honors_explicit_skip_stream_check_no_string(monkeypatch):
    monkeypatch.delenv("UP_SKIP_DESTROY", raising=False)
    monkeypatch.setenv("UP_SKIP_STREAM_CHECK", "no")

    _apply_unstable_map_env_defaults("Grid0828")


    assert os.environ.get("UP_SKIP_STREAM_CHECK") == "no"


def test_apply_env_defaults_overrides_other_truthy_values_to_one(monkeypatch):
    # Any value other than the explicit "0"/"false"/"no" escape hatch gets forced to "1".
    monkeypatch.delenv("UP_SKIP_DESTROY", raising=False)
    monkeypatch.setenv("UP_SKIP_STREAM_CHECK", "banana")

    _apply_unstable_map_env_defaults("Grid0828")


    assert os.environ.get("UP_SKIP_STREAM_CHECK") == "1"


def test_apply_env_defaults_does_not_override_preexisting_skip_destroy(monkeypatch):
    # UP_SKIP_DESTROY uses os.environ.setdefault, so an operator's explicit "0"
    # (force destroy even on unstable maps) must survive.
    monkeypatch.setenv("UP_SKIP_DESTROY", "0")
    monkeypatch.delenv("UP_SKIP_STREAM_CHECK", raising=False)

    _apply_unstable_map_env_defaults("Grid0828")


    assert os.environ.get("UP_SKIP_DESTROY") == "0"


# ---------------------------------------------------------------------------
# _handle_outer_stream_gate -- pure downstream consumer of args.skip_stream_check
# ---------------------------------------------------------------------------


def _gate_kwargs(tmp_path, **overrides):
    base = dict(
        args=SimpleNamespace(skip_stream_check=False, host="127.0.0.1", port=2000, frames=10, fps=10.0),
        out_dir=tmp_path,
        status={},
        pair_manifest={},
        perception_status={},
        stream_reachable=False,
        stream_optional=False,
        stream_port=2001,
    )
    base.update(overrides)
    return base


def test_stream_gate_reachable_short_circuits_regardless_of_flags(tmp_path):
    result = _handle_outer_stream_gate(**_gate_kwargs(tmp_path, stream_reachable=True))
    assert result is None
    # No failure artifacts should be written when the stream is reachable.
    assert not (tmp_path / "recording_summary.json").exists()


def test_stream_gate_skip_stream_check_true_short_circuits_even_if_unreachable(tmp_path):
    # This is the exact mechanism UP_SKIP_STREAM_CHECK=1 relies on: once it flows into
    # args.skip_stream_check, an unreachable stream port must not fail the run.
    args = SimpleNamespace(skip_stream_check=True, host="127.0.0.1", port=2000, frames=10, fps=10.0)
    result = _handle_outer_stream_gate(
        **_gate_kwargs(tmp_path, args=args, stream_reachable=False, stream_optional=False)
    )
    assert result is None
    assert not (tmp_path / "recording_summary.json").exists()


def test_stream_gate_optional_and_unreachable_warns_but_does_not_fail(tmp_path):
    perception_status = {}
    result = _handle_outer_stream_gate(
        **_gate_kwargs(
            tmp_path,
            stream_reachable=False,
            stream_optional=True,
            perception_status=perception_status,
        )
    )
    assert result is None
    assert any(
        w.startswith("stream_port_not_ready_optional:")
        for w in perception_status.get("warnings", [])
    )
    assert not (tmp_path / "recording_summary.json").exists()


def test_stream_gate_not_optional_and_unreachable_fails_and_writes_artifacts(tmp_path):
    status: dict = {}
    perception_status: dict = {}
    result = _handle_outer_stream_gate(
        **_gate_kwargs(
            tmp_path,
            stream_reachable=False,
            stream_optional=False,
            status=status,
            perception_status=perception_status,
        )
    )
    assert result == "carla_streaming_unreachable:127.0.0.1:2001"
    assert status["carla_failed"] is True
    assert status["failure_reason"] == "carla_streaming_unreachable:127.0.0.1:2001"
    assert perception_status["ok"] is False
    # Hard-failure path must produce the on-disk evidence bundle used by callers/CI.
    assert (tmp_path / "recording_summary.json").exists()
    assert (tmp_path / "carla_status.json").exists()


def test_stream_gate_unstable_map_defaults_applied_makes_stream_optional_end_to_end(
    tmp_path, monkeypatch
):
    # End-to-end wiring check: _apply_unstable_map_env_defaults's return value feeds
    # `stream_optional` (see run_perception_safe.main(): "stream_optional = bool(args.skip_stream_check
    # or unstable_map_defaults_applied)"). Simulate that composition directly here.
    monkeypatch.delenv("UP_SKIP_DESTROY", raising=False)
    monkeypatch.delenv("UP_SKIP_STREAM_CHECK", raising=False)

    unstable_map_defaults_applied = _apply_unstable_map_env_defaults("Grid0828")
    args = SimpleNamespace(skip_stream_check=False, host="127.0.0.1", port=2000, frames=10, fps=10.0)
    stream_optional = bool(args.skip_stream_check or unstable_map_defaults_applied)

    perception_status: dict = {}
    result = _handle_outer_stream_gate(
        **_gate_kwargs(
            tmp_path,
            args=args,
            stream_reachable=False,
            stream_optional=stream_optional,
            perception_status=perception_status,
        )
    )
    assert unstable_map_defaults_applied is True
    assert stream_optional is True
    assert result is None
    assert not (tmp_path / "recording_summary.json").exists()
