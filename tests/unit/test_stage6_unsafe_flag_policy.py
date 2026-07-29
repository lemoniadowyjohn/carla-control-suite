from __future__ import annotations

import pytest

from ultimate_pipeline.config.settings import Settings


UNSAFE_ENV_FLAGS = (
    "UP_ENABLE_UNSAFE_SHORT_SEGMENT_MERGE",
    "UP_ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE",
    "UP_ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING",
    "UP_ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP",
    "UP_ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE",
    "UP_ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK",
)

UNSAFE_SETTING_KEYS = (
    "ENABLE_UNSAFE_SHORT_SEGMENT_MERGE",
    "ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE",
    "ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING",
    "ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP",
    "ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE",
    "ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK",
)


@pytest.fixture(autouse=True)
def _clear_unsafe_env(monkeypatch):
    for env_key in UNSAFE_ENV_FLAGS:
        monkeypatch.delenv(env_key, raising=False)
    monkeypatch.delenv("UP_ENABLE_GEOMETRY_START_RECOMPUTE", raising=False)
    monkeypatch.delenv("UP_RELEASE_PROFILE", raising=False)


def test_stage6_unsafe_flags_default_false_and_snapshotted() -> None:
    settings = Settings()
    snapshot = settings.to_dict()

    for key in UNSAFE_SETTING_KEYS:
        assert getattr(settings, key) is False
        assert snapshot[key] is False


@pytest.mark.parametrize("env_key", UNSAFE_ENV_FLAGS)
def test_release_profile_rejects_unsafe_env_enable(monkeypatch, env_key: str) -> None:
    monkeypatch.setenv("UP_RELEASE_PROFILE", "STRUCTURAL_RELEASE")
    monkeypatch.setenv(env_key, "true")

    with pytest.raises(RuntimeError, match="Unsafe geometry mutations require"):
        Settings()


@pytest.mark.parametrize("env_key", UNSAFE_ENV_FLAGS)
def test_development_profile_rejects_unsafe_env_enable(monkeypatch, env_key: str) -> None:
    monkeypatch.setenv("UP_RELEASE_PROFILE", "DEVELOPMENT")
    monkeypatch.setenv(env_key, "true")

    with pytest.raises(RuntimeError, match="EXPERIMENTAL_UNSAFE"):
        Settings()


def test_experimental_profile_can_enable_individual_unsafe_flag(monkeypatch) -> None:
    monkeypatch.setenv("UP_RELEASE_PROFILE", "EXPERIMENTAL_UNSAFE")
    monkeypatch.setenv("UP_THESIS_STRICT", "false")
    monkeypatch.setenv("UP_ENABLE_UNSAFE_SHORT_SEGMENT_MERGE", "true")

    settings = Settings()

    assert settings.RELEASE_PROFILE == "EXPERIMENTAL_UNSAFE"
    assert settings.ENABLE_UNSAFE_SHORT_SEGMENT_MERGE is True
    assert settings.to_dict()["ENABLE_UNSAFE_SHORT_SEGMENT_MERGE"] is True


def test_thesis_strict_rejects_experimental_unsafe_enable(monkeypatch) -> None:
    monkeypatch.setenv("UP_RELEASE_PROFILE", "EXPERIMENTAL_UNSAFE")
    monkeypatch.setenv("UP_THESIS_STRICT", "true")
    monkeypatch.setenv("UP_ENABLE_UNSAFE_SHORT_SEGMENT_MERGE", "true")

    with pytest.raises(RuntimeError, match="EXPERIMENTAL_UNSAFE"):
        Settings()


def test_invalid_unsafe_env_value_fails_validation(monkeypatch) -> None:
    monkeypatch.setenv("UP_ENABLE_UNSAFE_SHORT_SEGMENT_MERGE", "maybe")

    with pytest.raises(RuntimeError, match="UP_ENABLE_UNSAFE_SHORT_SEGMENT_MERGE"):
        Settings()
