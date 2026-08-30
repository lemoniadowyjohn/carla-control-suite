# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/utils/paths.py.

Live: main_pipeline.py imports city_dir directly at module level (line
64). Zero prior test coverage. No bugs found on review -- repo_root's
walk-up-until-ultimate_pipeline/-exists logic and the env-var resolution
order in cities_root/city_dir/resolve_path are all correct.
"""
from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.utils.paths import (
    cities_root,
    city_dir,
    repo_root,
    resolve_city_path,
    resolve_path,
)


def test_repo_root_finds_the_directory_containing_ultimate_pipeline():
    root = repo_root()
    assert (root / "ultimate_pipeline").is_dir()


def test_cities_root_prefers_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("UP_CITIES_DIR", str(tmp_path))
    assert cities_root() == tmp_path


def test_cities_root_env_override_is_repo_relative_when_not_absolute(monkeypatch):
    monkeypatch.setenv("UP_CITIES_DIR", "some/relative/cities")
    assert cities_root() == repo_root() / "some/relative/cities"


def test_cities_root_falls_back_to_package_cities_dir_when_present(monkeypatch):
    monkeypatch.delenv("UP_CITIES_DIR", raising=False)
    root = repo_root()
    pkg_cities = root / "ultimate_pipeline" / "cities"
    if pkg_cities.is_dir():
        assert cities_root() == pkg_cities
    else:
        assert cities_root() == root / "cities"


def test_city_dir_defaults_to_ingolstadt(monkeypatch):
    monkeypatch.delenv("UP_CITY", raising=False)
    assert city_dir().name == "ingolstadt"


def test_city_dir_uses_explicit_argument_over_env(monkeypatch):
    monkeypatch.setenv("UP_CITY", "other_city")
    assert city_dir("explicit_city").name == "explicit_city"


def test_city_dir_uses_env_when_no_argument(monkeypatch):
    monkeypatch.setenv("UP_CITY", "env_city")
    assert city_dir().name == "env_city"


def test_city_dir_blank_argument_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("UP_CITY", raising=False)
    assert city_dir("   ").name == "ingolstadt"


def test_resolve_path_none_returns_default(tmp_path):
    default = tmp_path / "default_dir"
    assert resolve_path(None, default=default) == default


def test_resolve_path_empty_string_returns_default(tmp_path):
    default = tmp_path / "default_dir"
    assert resolve_path("", default=default) == default


def test_resolve_path_absolute_path_returned_as_is(tmp_path):
    abs_path = tmp_path / "somewhere"
    assert resolve_path(str(abs_path), default=tmp_path) == abs_path


def test_resolve_path_relative_path_is_repo_relative(tmp_path):
    result = resolve_path("relative/sub/dir", default=tmp_path)
    assert result == repo_root() / "relative/sub/dir"


def test_resolve_city_path_defaults_to_city_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("UP_CITY", raising=False)
    assert resolve_city_path(None, city="testcity") == city_dir("testcity")


def test_resolve_city_path_absolute_value_returned_as_is(tmp_path):
    abs_path = tmp_path / "explicit"
    assert resolve_city_path(str(abs_path)) == abs_path
