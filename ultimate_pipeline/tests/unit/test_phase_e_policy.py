# E5 policy: roundabout reconstruction stays disabled unless its full
# fixture suite passes.  Every release profile and the default settings
# object must gate reconstruction off; enabling is an explicit opt-in only.
from __future__ import annotations

from ultimate_pipeline.config.settings import Settings, SETTINGS

RELEASE_PROFILE_NAMES = (
    "DEVELOPMENT",
    "EXPERIMENTAL_UNSAFE",
    "STRUCTURAL_RELEASE",
    "CARLA_RELEASE",
    "VISUAL_RELEASE",
    "PERCEPTION_RELEASE",
)


def test_roundabout_reconstruction_disabled_in_every_release_profile() -> None:
    profiles = getattr(Settings, "RELEASE_PROFILES", None)
    assert profiles is not None
    for name in RELEASE_PROFILE_NAMES:
        assert name in profiles, f"missing release profile {name}"
        assert (
            profiles[name].get("ENABLE_ROUNDABOUT_RECONSTRUCTION") is False
        ), f"roundabout reconstruction must be OFF in {name}"


def test_roundabout_reconstruction_disabled_by_default_settings() -> None:
    assert getattr(SETTINGS, "ENABLE_ROUNDABOUT_RECONSTRUCTION", True) is False


def test_stage04_gates_reconstruction_behind_explicit_flag() -> None:
    import inspect

    from ultimate_pipeline.pipeline_stages.stage_04_enrichment import (
        _step4_enrichment,
    )

    src = inspect.getsource(_step4_enrichment)
    assert "ENABLE_ROUNDABOUT_RECONSTRUCTION" in src
    assert "RoundaboutReconstructor.reconstruct" in src
    assert '"Roundabout reconstruction disabled."' in src or (
        "Roundabout reconstruction disabled" in src
    )


def test_roundabout_ring_validation_negative_control() -> None:
    import xml.etree.ElementTree as ET

    from ultimate_pipeline.topology.topology_validation import (
        validate_roundabout_ring,
    )

    def _road(rid: str, succ: str | None, pred: str | None) -> ET.Element:
        r = ET.Element("road", {"id": rid, "length": "50"})
        link = ET.SubElement(r, "link")
        if succ is not None:
            ET.SubElement(
                link, "successor", {"elementType": "road", "elementId": succ}
            )
        if pred is not None:
            ET.SubElement(
                link, "predecessor", {"elementType": "road", "elementId": pred}
            )
        return r

    roads = {
        "1": _road("1", "2", None),
        "2": _road("2", "3", None),
        "3": _road("3", "4", None),
        "4": _road("4", None, "1"),
    }
    res = validate_roundabout_ring(["1", "2", "3", "4"], roads)
    assert res["closed"] is True

    broken = dict(roads)
    broken["2"] = _road("2", None, None)
    res2 = validate_roundabout_ring(["1", "2", "3", "4"], broken)
    assert res2["closed"] is False
