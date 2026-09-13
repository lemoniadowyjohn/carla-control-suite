from ultimate_pipeline.tools.structure_elevation_remediation_probe import (
    failure_characterization,
    incomplete_characterization,
)


THRESHOLDS = {"min_bridge_clearance_m": 0.5, "min_tunnel_cover_m": 0.5}


def test_failure_characterization_distinguishes_near_miss_and_mixed_sign() -> None:
    near = failure_characterization(
        {"class": "bridge"}, [{"status": "EVALUABLE", "delta_m": 0.38}], THRESHOLDS
    )
    mixed = failure_characterization(
        {"class": "elevated"},
        [
            {"status": "EVALUABLE", "delta_m": -0.2},
            {"status": "EVALUABLE", "delta_m": 0.6},
        ],
        THRESHOLDS,
    )

    assert near["primary_bucket"] == "near_miss"
    assert mixed["primary_bucket"] == "mixed_sign"
    assert mixed["terrain_crossing"] is True


def test_incomplete_characterization_keeps_missing_evidence_distinct() -> None:
    assert incomplete_characterization(
        {"sample_count": 1, "evaluable_sample_count": 1}, 2
    ) == "insufficient_interior_geometry_samples"
    assert incomplete_characterization(
        {"sample_count": 3, "evaluable_sample_count": 0, "missing_terrain_count": 3}, 2
    ) == "terrain_out_of_coverage_or_nodata"
