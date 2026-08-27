"""Map identity name-normalization/matching logic in
ultimate_pipeline/carla_tools/map_registry.py -- used by map_only_probe.py and
run_perception_safe.py to verify CARLA actually loaded the requested map (not a
silently-wrong one). This half of the module (everything except the C13 content-addressed
pin registry, already covered by test_map_registry_pinning.py) had zero test coverage on
this branch -- a stale .pyc in __pycache__ (test_map_registry.py) with no matching .py
source shows a test for it existed at some point but was never carried onto this branch.
"""
from __future__ import annotations

from ultimate_pipeline.carla_tools.map_registry import (
    COOKED_MAP_ALIASES,
    XODR_ONLY_MAPS,
    normalize_map_name,
    get_canonical_name,
    is_cooked_map,
    is_xodr_only_map,
    get_map_type,
    resolve_expected_names,
    map_names_match,
    get_load_world_candidates,
    safe_get_available_maps,
    resolve_available_load_world_targets,
)


# ---------------------------------------------------------------------------
# normalize_map_name
# ---------------------------------------------------------------------------

def test_normalize_strips_game_carla_maps_prefix():
    assert normalize_map_name("/Game/Carla/Maps/Town10HD_Opt") == "town10hd_opt"


def test_normalize_strips_carla_maps_prefix():
    assert normalize_map_name("Carla/Maps/Grid0828") == "grid0828"


def test_normalize_strips_bare_game_prefix():
    assert normalize_map_name("/Game/Grid0828") == "grid0828"


def test_normalize_strips_leading_slash_with_no_known_prefix():
    assert normalize_map_name("/Grid0828") == "grid0828"


def test_normalize_handles_carla_real_return_format():
    # CARLA's client.get_world().get_map().name for a cooked map returns this
    # "{MapName}/Maps/{MapName}/{MapName}" pattern -- the module's own docstring
    # documents this exact case.
    assert normalize_map_name("Grid0828/Maps/Grid0828/Grid0828") == "grid0828"


def test_normalize_plain_name_just_lowercases():
    assert normalize_map_name("Town01") == "town01"


def test_normalize_empty_string_returns_empty():
    assert normalize_map_name("") == ""


def test_normalize_none_returns_empty():
    assert normalize_map_name(None) == ""


# ---------------------------------------------------------------------------
# get_canonical_name / is_cooked_map / is_xodr_only_map / get_map_type
# ---------------------------------------------------------------------------

def test_get_canonical_name_resolves_alias_form():
    assert get_canonical_name("Carla/Maps/Grid0828") == "Grid0828"


def test_get_canonical_name_case_insensitive():
    assert get_canonical_name("grid0828") == "Grid0828"


def test_get_canonical_name_unknown_map_returns_none():
    assert get_canonical_name("NotARealMap") is None


def test_is_cooked_map_true_for_every_registered_canonical_name():
    for canonical in COOKED_MAP_ALIASES:
        assert is_cooked_map(canonical) is True, canonical


def test_is_cooked_map_true_for_an_alias_variant():
    assert is_cooked_map("/Game/Carla/Maps/Grid0828") is True


def test_is_cooked_map_false_for_unknown_map():
    assert is_cooked_map("SomeRandomMap") is False


def test_is_xodr_only_map_false_when_registry_empty():
    # XODR_ONLY_MAPS is currently empty (Grid maps are cooked, not XODR-only) --
    # this pins that documented current state so a future change is visible here.
    assert XODR_ONLY_MAPS == {}
    assert is_xodr_only_map("Grid0828") is False


def test_get_map_type_cooked_for_known_map():
    assert get_map_type("Grid0828") == "cooked"


def test_get_map_type_unknown_for_unregistered_map():
    assert get_map_type("SomeRandomMap") == "unknown"


# ---------------------------------------------------------------------------
# resolve_expected_names
# ---------------------------------------------------------------------------

def test_resolve_expected_names_known_map_includes_all_its_aliases():
    result = resolve_expected_names("Grid0828")
    assert result["canonical_name"] == "Grid0828"
    assert result["map_type"] == "cooked"
    assert result["expected_raw"] == "Grid0828"
    for alias in COOKED_MAP_ALIASES["Grid0828"]:
        assert normalize_map_name(alias) in result["acceptable_normalized_set"]


def test_resolve_expected_names_unknown_map_falls_back_to_exact_normalized_form():
    result = resolve_expected_names("SomeRandomMap")
    assert result["canonical_name"] is None
    assert result["acceptable_normalized_set"] == frozenset({"somerandommap"})
    assert result["expected_raw"] == "SomeRandomMap"  # uses original request, not a canonical


# ---------------------------------------------------------------------------
# map_names_match
# ---------------------------------------------------------------------------

def test_map_names_match_exact():
    assert map_names_match("Town01", "Town01") is True


def test_map_names_match_via_carla_real_return_format():
    assert map_names_match("Grid0828/Maps/Grid0828/Grid0828", "Grid0828") is True


def test_map_names_match_via_shared_canonical_name():
    # Two different alias spellings of the SAME canonical map must match each other.
    assert map_names_match("/Game/Carla/Maps/Grid0828", "Carla/Maps/Grid0828") is True


def test_map_names_match_false_for_genuinely_different_maps():
    assert map_names_match("Town01", "Town02") is False


def test_map_names_match_grid0821_and_grid0828_do_not_cross_match_by_name():
    # Real drift risk this session's memory already documents at the content level
    # (Grid0821.xodr/Grid0828.xodr are byte-identical files under two names) -- but at
    # the NAME level, map_names_match must still treat them as distinct registry entries,
    # not silently interchangeable, since a caller asking for one and getting the other
    # loaded is exactly the kind of drift this module exists to catch.
    assert map_names_match("Grid0821", "Grid0828") is False


# ---------------------------------------------------------------------------
# get_load_world_candidates
# ---------------------------------------------------------------------------

def test_get_load_world_candidates_known_map_leads_with_canonical():
    candidates = get_load_world_candidates("carla/maps/grid0828")
    assert candidates[0] == "Grid0828"


def test_get_load_world_candidates_unknown_map_returns_just_the_request():
    assert get_load_world_candidates("SomeRandomMap") == ["SomeRandomMap"]


# ---------------------------------------------------------------------------
# safe_get_available_maps (mocked client, no live CARLA needed)
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self, maps, raise_on_query=False):
        self._maps = maps
        self._raise_on_query = raise_on_query
        self.timeouts_set = []

    def set_timeout(self, value):
        self.timeouts_set.append(value)

    def get_available_maps(self):
        if self._raise_on_query:
            raise RuntimeError("simulated RPC failure")
        return self._maps


def test_safe_get_available_maps_success():
    client = _FakeClient(["Carla/Maps/Grid0828", "Carla/Maps/Town01"])
    result = safe_get_available_maps(client)
    assert result["ok"] is True
    assert result["available_maps_count"] == 2
    assert "grid0828" in result["normalized_maps"]
    assert result["available_maps_hash"]  # non-empty
    # timeout must be restored even on the success path
    assert client.timeouts_set[-1] == 20.0


def test_safe_get_available_maps_handles_rpc_failure_without_raising():
    client = _FakeClient([], raise_on_query=True)
    result = safe_get_available_maps(client)
    assert result["ok"] is False
    assert result["error"]
    assert result["maps"] == []
    # timeout restore must still happen in the finally block even on failure
    assert client.timeouts_set[-1] == 20.0


# ---------------------------------------------------------------------------
# resolve_available_load_world_targets
# ---------------------------------------------------------------------------

def test_resolve_available_load_world_targets_matches_real_carla_format():
    available = ["Grid0828/Maps/Grid0828/Grid0828", "Town01/Maps/Town01/Town01"]
    result = resolve_available_load_world_targets("Grid0828", available)
    assert "Grid0828/Maps/Grid0828/Grid0828" in result["matched_targets"]
    assert "Town01/Maps/Town01/Town01" not in result["matched_targets"]


def test_resolve_available_load_world_targets_no_match_when_map_not_advertised():
    available = ["Town01/Maps/Town01/Town01"]
    result = resolve_available_load_world_targets("Grid0828", available)
    assert result["matched_targets"] == []
