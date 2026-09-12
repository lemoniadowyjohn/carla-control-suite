from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.quality.candidate_regression_gate import (
    compare_candidate_to_baseline,
    PROTECTED_KEYS,
)


def _write_map(path: Path, *, hdg: str = "0", junction: str = "-1") -> None:
    path.write_text(
        f"""<OpenDRIVE><road name="" length="10" id="1" junction="{junction}">
        <link>
          <predecessor elementType="road" elementId="2" contactPoint="end"/>
        </link>
        <planView><geometry s="0" x="0" y="0" hdg="{hdg}" length="10"><line/></geometry></planView>
        <elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile>
        <lanes><laneSection s="0"><right><lane id="-1" type="driving">
        <width sOffset="0" a="3.5" b="0" c="0" d="0"/>
        </lane></right></laneSection></lanes>
        </road></OpenDRIVE>""",
        encoding="utf-8",
    )


def test_identical_candidate_is_regression_clean(tmp_path):
    baseline = tmp_path / "baseline.xodr"
    candidate = tmp_path / "candidate.xodr"
    _write_map(baseline)
    _write_map(candidate)

    result = compare_candidate_to_baseline(
        str(baseline), str(candidate), out_dir=str(tmp_path / "work")
    )

    assert result["verdict"] == "REGRESSION_CLEAN"
    assert result["identity"]["protected_ok"] is True
    assert all(result["identity"]["protected_hash_matches"].values())
    assert result["loadability"]["loadability_ok"] is True
    assert result["loadability"]["new_or_exceeded_error_classes"] == {}


def test_planview_drift_is_regression_detected(tmp_path):
    """A candidate whose planView geometry silently differs from its
    baseline (e.g. an accidental re-derivation instead of a byte-preserving
    copy) must be caught -- this is exactly the class of silent drift
    Phase G's protected-hash freeze exists to prevent."""
    baseline = tmp_path / "baseline.xodr"
    candidate = tmp_path / "candidate.xodr"
    _write_map(baseline, hdg="0")
    _write_map(candidate, hdg="0.5")  # planview heading silently changed

    result = compare_candidate_to_baseline(
        str(baseline), str(candidate), out_dir=str(tmp_path / "work")
    )

    assert result["verdict"] == "REGRESSION_DETECTED"
    assert result["identity"]["protected_ok"] is False
    assert result["identity"]["protected_hash_matches"]["planview_hash"] is False
    # only the domain that actually changed should be flagged
    assert result["identity"]["protected_hash_matches"]["road_length_hash"] is True
    assert result["identity"]["protected_hash_matches"]["elevation_profile_hash"] is True


def test_all_protected_keys_are_checked(tmp_path):
    baseline = tmp_path / "baseline.xodr"
    _write_map(baseline)
    result = compare_candidate_to_baseline(
        str(baseline), str(baseline), out_dir=str(tmp_path / "work")
    )
    assert set(result["identity"]["protected_hash_matches"].keys()) == set(PROTECTED_KEYS)


def test_no_out_dir_uses_a_temp_directory(tmp_path):
    """Callers should not be forced to manage a work directory for a
    one-off comparison."""
    baseline = tmp_path / "baseline.xodr"
    candidate = tmp_path / "candidate.xodr"
    _write_map(baseline)
    _write_map(candidate)

    result = compare_candidate_to_baseline(str(baseline), str(candidate))

    assert result["verdict"] == "REGRESSION_CLEAN"
    assert result["work_dir"]
