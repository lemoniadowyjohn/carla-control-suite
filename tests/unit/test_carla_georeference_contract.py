"""Tests for the georeference fail-closed contract.

Cases are the authoritative strings taken from the CARLA 0.9.16 tree, not
invented ones:

  * ``+proj=tmerc``            -- what Ingolstadt's map of record actually has
  * ``+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m
    +no_defs`` -- what Town01.xodr has
  * ``+lat_0=4.9e+1 +lon_0=8.0e+0`` -- what the osm2odr test fixture has
"""
from __future__ import annotations

import pytest

from tools.carla_georeference_contract import (
    LEGACY_FALLBACK_LAT,
    LEGACY_FALLBACK_LON,
    GeoreferenceError,
    parse_georeference_legacy,
    parse_georeference_strict,
)

INGOLSTADT_ACTUAL = "+proj=tmerc"          # the defect, verbatim from the .xodr
TOWN01 = ("+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 "
          "+datum=WGS84 +units=m +no_defs")
OSM2ODR_FIXTURE = "+lat_0=4.9000000000000000e+1 +lon_0=8.0000000000000000e+0"
INGOLSTADT_TRUTH = "+proj=tmerc +lat_0=48.7664 +lon_0=11.4255"


class TestIncompleteIsRejected:
    def test_bare_proj_tmerc_is_rejected(self):
        with pytest.raises(GeoreferenceError) as e:
            parse_georeference_strict(INGOLSTADT_ACTUAL)
        assert "incomplete" in str(e.value)
        assert "+lat_0" in str(e.value) and "+lon_0" in str(e.value)

    def test_missing_lon_is_rejected(self):
        with pytest.raises(GeoreferenceError):
            parse_georeference_strict("+proj=tmerc +lat_0=48.7")

    def test_missing_lat_is_rejected(self):
        with pytest.raises(GeoreferenceError):
            parse_georeference_strict("+proj=tmerc +lon_0=11.4")

    @pytest.mark.parametrize("bad", ["", "   ", None])
    def test_empty_or_absent_is_rejected(self, bad):
        with pytest.raises(GeoreferenceError):
            parse_georeference_strict(bad)


class TestMalformedIsRejected:
    def test_non_numeric_lat_is_rejected(self):
        with pytest.raises(GeoreferenceError) as e:
            parse_georeference_strict("+lat_0=abc +lon_0=11.4")
        assert "not a number" in str(e.value)

    def test_nan_lat_is_rejected(self):
        with pytest.raises(GeoreferenceError) as e:
            parse_georeference_strict("+lat_0=nan +lon_0=11.4")
        assert "not finite" in str(e.value)

    def test_infinite_lon_is_rejected(self):
        with pytest.raises(GeoreferenceError):
            parse_georeference_strict("+lat_0=48.7 +lon_0=inf")

    def test_out_of_range_lat_is_rejected(self):
        with pytest.raises(GeoreferenceError) as e:
            parse_georeference_strict("+lat_0=1234 +lon_0=11.4")
        assert "outside [-90, 90]" in str(e.value)

    def test_out_of_range_lon_is_rejected(self):
        with pytest.raises(GeoreferenceError) as e:
            parse_georeference_strict("+lat_0=48.7 +lon_0=999")
        assert "outside [-180, 180]" in str(e.value)

    def test_token_without_equals_is_ignored_not_fatal(self):
        # Mirrors the C++ grammar: '+k' has no '=' so it is skipped, but the
        # required keys are present and valid, so the string parses fine.
        g = parse_georeference_strict("+proj=tmerc +k +lat_0=48.7 +lon_0=11.4")
        assert g.latitude == pytest.approx(48.7)
        assert g.longitude == pytest.approx(11.4)
        assert "+k" not in g.tokens


class TestValidIsAccepted:
    def test_town01_full_string(self):
        g = parse_georeference_strict(TOWN01)
        assert g.latitude == 0.0
        assert g.longitude == 0.0
        assert g.tokens["+datum"] == "WGS84"

    def test_osm2odr_test_fixture(self):
        g = parse_georeference_strict(OSM2ODR_FIXTURE)
        assert g.latitude == pytest.approx(49.0)
        assert g.longitude == pytest.approx(8.0)

    def test_ingolstadt_authoritative_values(self):
        g = parse_georeference_strict(INGOLSTADT_TRUTH)
        assert g.latitude == pytest.approx(48.7664)
        assert g.longitude == pytest.approx(11.4255)

    def test_roundtrip_to_string(self):
        g = parse_georeference_strict(TOWN01)
        again = parse_georeference_strict(g.as_carla_string())
        assert (again.latitude, again.longitude) == (g.latitude, g.longitude)

    def test_scientific_notation_exponent_is_accepted(self):
        g = parse_georeference_strict(OSM2ODR_FIXTURE)
        assert g.latitude == pytest.approx(49.0)


class TestLegacyDefectIsPinned:
    """Pin the exact behaviour being removed, so its removal is verifiable."""

    def test_legacy_silently_defaults_on_ingolstadt_string(self):
        g = parse_georeference_legacy(INGOLSTADT_ACTUAL)
        assert g.latitude == LEGACY_FALLBACK_LAT == 42.0
        assert g.longitude == LEGACY_FALLBACK_LON == 2.0
        assert g.tokens["_fallback"] == "true"

    def test_fallback_is_geographically_wrong_for_ingolstadt(self):
        got = parse_georeference_legacy(INGOLSTADT_ACTUAL)
        want = parse_georeference_strict(INGOLSTADT_TRUTH)
        # ~6.77 degrees of latitude is roughly 752 km
        assert abs(got.latitude - want.latitude) > 6.0
        assert abs(got.longitude - want.longitude) > 9.0

    def test_strict_and_legacy_agree_when_complete(self):
        a = parse_georeference_strict(TOWN01)
        b = parse_georeference_legacy(TOWN01)
        assert (a.latitude, a.longitude) == (b.latitude, b.longitude)

    def test_strict_and_legacy_disagree_only_when_incomplete(self):
        with pytest.raises(GeoreferenceError):
            parse_georeference_strict(INGOLSTADT_ACTUAL)
        assert parse_georeference_legacy(INGOLSTADT_ACTUAL).latitude == 42.0


class TestNoSilentFallbackInvariant:
    def test_strict_parser_never_returns_the_legacy_constants(self):
        """Exhaustive-ish: no accepted input may yield 42.0/2.0 by substitution."""
        for text in [TOWN01, OSM2ODR_FIXTURE, INGOLSTADT_TRUTH,
                     "+lat_0=42.0 +lon_0=2.0"]:
            g = parse_georeference_strict(text)
            # if a caller really passes 42/2 that is an explicit choice,
            # never a substitution, so no _fallback marker may appear
            assert "_fallback" not in g.tokens

    def test_missing_required_key_never_yields_a_value(self):
        with pytest.raises(GeoreferenceError):
            parse_georeference_strict("+proj=tmerc +k=1 +x_0=0 +y_0=0 +units=m")