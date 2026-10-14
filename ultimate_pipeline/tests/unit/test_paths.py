import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from ultimate_pipeline.utils.paths import (
    repo_root,
    cities_root,
    city_dir,
    resolve_path,
    resolve_city_path,
    PathLike,
)


class TestRepoRoot:
    def test_returns_path(self):
        root = repo_root()
        assert isinstance(root, Path)
        assert root.exists()
        assert root.is_dir()

    def test_contains_ultimate_pipeline(self):
        root = repo_root()
        assert (root / "ultimate_pipeline").is_dir()


class TestCitiesRoot:
    def test_env_var_takes_precedence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"UP_CITIES_DIR": tmpdir}):
                root = cities_root()
                assert root == Path(tmpdir)

    def test_env_var_relative_to_repo(self):
        with patch.dict(os.environ, {"UP_CITIES_DIR": "relative_cities"}):
            root = cities_root()
            expected = repo_root() / "relative_cities"
            assert root == expected

    def test_fallback_to_pkg_cities(self):
        with patch.dict(os.environ, {}, clear=True):
            # Mock the pkg_cities check
            root = cities_root()
            # Should return either pkg_cities or repo_root/cities
            assert root.exists() or root.parent.exists()


class TestCityDir:
    def test_default_city(self):
        with patch.dict(os.environ, {}, clear=True):
            d = city_dir(None)
            assert isinstance(d, Path)
            assert d.name == "ingolstadt"

    def test_env_city(self):
        with patch.dict(os.environ, {"UP_CITY": "munich"}):
            d = city_dir(None)
            assert d.name == "munich"

    def test_explicit_city(self):
        d = city_dir("berlin")
        assert d.name == "berlin"

    def test_empty_string_fallback(self):
        d = city_dir("")
        assert d.name == "ingolstadt"

    def test_whitespace_stripped(self):
        d = city_dir("  tokyo  ")
        assert d.name == "tokyo"


class TestResolvePath:
    def test_none_returns_default(self):
        default = Path("/default/path")
        result = resolve_path(None, default=default)
        assert result == default

    def test_empty_string_returns_default(self):
        default = Path("/default/path")
        result = resolve_path("", default=default)
        assert result == default

    def test_absolute_path_returns_as_is(self):
        # On Windows, absolute paths have drive letters. Use a platform-appropriate absolute path.
        import os
        if os.name == 'nt':
            abs_path = Path("C:/absolute/path")
        else:
            abs_path = Path("/absolute/path")
        result = resolve_path(abs_path, default=Path("/default"))
        assert result == abs_path

    def test_relative_path_resolved_against_repo_root(self):
        with patch("ultimate_pipeline.utils.paths.repo_root", return_value=Path("/repo")):
            result = resolve_path("relative/path", default=Path("/default"))
            assert result == Path("/repo/relative/path")

    def test_pathlib_path_input(self):
        with patch("ultimate_pipeline.utils.paths.repo_root", return_value=Path("/repo")):
            result = resolve_path(Path("relative/path"), default=Path("/default"))
            assert result == Path("/repo/relative/path")


class TestResolveCityPath:
    def test_backwards_compat_alias(self):
        with patch.dict(os.environ, {"UP_CITY": "testcity"}):
            result = resolve_city_path("custom/path", city="ignored")
            expected = repo_root() / "custom/path"
            assert result == expected

    def test_none_uses_city_dir(self):
        with patch.dict(os.environ, {"UP_CITY": "mycity"}):
            with patch("ultimate_pipeline.utils.paths.cities_root", return_value=Path("/cities")):
                result = resolve_city_path(None, city="mycity")
                assert result == Path("/cities/mycity")


class TestPathLikeType:
    def test_union_includes_none(self):
        # This is a type hint test - just verify the type alias exists
        assert PathLike is not None