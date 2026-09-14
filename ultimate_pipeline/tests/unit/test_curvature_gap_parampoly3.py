from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from ultimate_pipeline.domain_gap.curvature_gap import CurvatureGap, _extract_curvatures


def _write_arc_xodr(path: Path, curvatures: list[float]) -> None:
    root = ET.Element("OpenDRIVE")
    for idx, k in enumerate(curvatures):
        road = ET.SubElement(
            root, "road",
            attrib={"name": f"r{idx}", "length": "10.0", "id": str(idx), "junction": "-1"},
        )
        plan_view = ET.SubElement(road, "planView")
        geom = ET.SubElement(
            plan_view, "geometry",
            attrib={"s": "0", "x": "0", "y": str(float(idx) * 20.0), "hdg": "0", "length": "10.0"},
        )
        ET.SubElement(geom, "arc", attrib={"curvature": str(k)})
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _write_parampoly3_xodr(
    path: Path,
    roads: list[dict[str, object]],
) -> None:
    root = ET.Element("OpenDRIVE")
    for idx, spec in enumerate(roads):
        road = ET.SubElement(
            root,
            "road",
            attrib={
                "name": f"r{idx}",
                "length": str(spec.get("length", 10.0)),
                "id": str(idx),
                "junction": "-1",
            },
        )
        plan_view = ET.SubElement(road, "planView")
        geom = ET.SubElement(
            plan_view,
            "geometry",
            attrib={
                "s": "0",
                "x": "0",
                "y": str(spec.get("y", 0.0)),
                "hdg": "0",
                "length": str(spec.get("length", 10.0)),
            },
        )
        ET.SubElement(
            geom,
            "paramPoly3",
            attrib={
                "aU": "0",
                "bU": str(spec.get("bU", 1.0)),
                "cU": str(spec.get("cU", 0.0)),
                "dU": str(spec.get("dU", 0.0)),
                "aV": "0",
                "bV": str(spec.get("bV", 0.0)),
                "cV": str(spec.get("cV", 0.0)),
                "dV": str(spec.get("dV", 0.0)),
                "pRange": str(spec.get("pRange", "arcLength")),
            },
        )
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_straight_parampoly3_produces_zero_curvature(tmp_path: Path) -> None:
    manual = tmp_path / "manual_straight.xodr"
    auto = tmp_path / "auto_straight.xodr"
    straight = [
        {"length": 10.0, "bU": 1.0, "cU": 0.0, "dU": 0.0, "bV": 0.0, "cV": 0.0, "dV": 0.0}
    ]
    _write_parampoly3_xodr(manual, straight)
    _write_parampoly3_xodr(auto, straight)

    result = CurvatureGap.compute(str(manual), str(auto))

    assert result["samples_manual"] > 0
    assert result["samples_auto"] > 0
    assert result["mean_manual"] == 0.0
    assert result["mean_auto"] == 0.0
    assert result["std_manual"] == 0.0
    assert result["std_auto"] == 0.0


def test_curved_parampoly3_produces_nonzero_curvature(tmp_path: Path) -> None:
    manual = tmp_path / "manual_curved.xodr"
    auto = tmp_path / "auto_curved.xodr"
    straight = [
        {"length": 10.0, "bU": 1.0, "cU": 0.0, "dU": 0.0, "bV": 0.0, "cV": 0.0, "dV": 0.0}
    ]
    curved = [
        {"length": 10.0, "bU": 1.0, "cU": 0.0, "dU": 0.0, "bV": 0.0, "cV": 0.05, "dV": 0.0}
    ]
    _write_parampoly3_xodr(manual, straight)
    _write_parampoly3_xodr(auto, curved)

    result = CurvatureGap.compute(str(manual), str(auto))

    assert result["samples_auto"] > 0
    assert result["mean_auto"] > 0.0
    assert result["std_auto"] >= 0.0


def test_extract_curvatures_nonzero_for_parampoly3_only_map(tmp_path: Path) -> None:
    auto = tmp_path / "auto_parampoly3_only.xodr"
    _write_parampoly3_xodr(
        auto,
        [
            {"length": 10.0, "y": 0.0, "bU": 1.0, "cU": 0.0, "dU": 0.0, "bV": 0.0, "cV": 0.05, "dV": 0.0},
            {"length": 10.0, "y": 5.0, "bU": 1.0, "cU": 0.0, "dU": 0.0, "bV": 0.0, "cV": 0.03, "dV": 0.0},
            {"length": 10.0, "y": 10.0, "bU": 1.0, "cU": 0.0, "dU": 0.0, "bV": 0.0, "cV": 0.07, "dV": 0.0},
        ],
    )

    root = ET.parse(auto).getroot()
    values = _extract_curvatures(root, include_lines=True)

    assert len(values) > 0
    assert max(values) > 0.0


# ---------------------------------------------------------------------------
# CurvatureGap.compute() built its histograms with np.histogram(density=True)
# (a continuous density that integrates to 1 over the bin width) and fed them
# straight into a discrete KL-divergence sum formula that requires
# probability MASSES (values that sum to 1). That silently inflated the
# reported kl_divergence by a factor of 1/bin_width -- and this exact
# function is the documented source of the thesis's cited
# "corrected_curvature_kl_divergence" claim, so the miscalibration was live
# in a real reported metric, not just a theoretical concern.
# ---------------------------------------------------------------------------

def test_kl_divergence_is_probability_mass_based_not_density_based(tmp_path: Path) -> None:
    manual = tmp_path / "manual_arcs.xodr"
    auto = tmp_path / "auto_arcs.xodr"
    manual_curvatures = [0.01, 0.01, 0.02, 0.03, 0.03, 0.03]
    auto_curvatures = [0.01, 0.02, 0.02, 0.04, 0.04, 0.05]
    _write_arc_xodr(manual, manual_curvatures)
    _write_arc_xodr(auto, auto_curvatures)

    result = CurvatureGap.compute(str(manual), str(auto))

    bins = result["bins"]
    max_val = max(max(manual_curvatures), max(auto_curvatures), 1e-6)
    hist_m_counts, edges = np.histogram(manual_curvatures, bins=bins, range=(0.0, max_val))
    hist_a_counts, _ = np.histogram(auto_curvatures, bins=edges)
    p = hist_m_counts / hist_m_counts.sum()
    q = hist_a_counts / hist_a_counts.sum()
    eps = 1e-12
    expected_kl = float(np.sum((p + eps) * np.log((p + eps) / (q + eps))))

    assert result["kl_divergence"] == pytest.approx(expected_kl, rel=1e-9)
    # Pre-fix, the density-based bug returned ~20555 for this exact input
    # (verified via git-stash RED check) instead of the correct ~13.6 --
    # roughly 1500x inflated, driven by the same 1/bin_width factor.
    assert result["kl_divergence"] < 100.0
