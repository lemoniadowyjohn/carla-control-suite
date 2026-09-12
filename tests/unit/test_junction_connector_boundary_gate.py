from pathlib import Path

from ultimate_pipeline.core.validation_report import ValidationReport
from ultimate_pipeline.quality.check_geometric_continuity import check_geometric_continuity
from ultimate_pipeline.quality.quality_gate_manager import QualityGateManager


def _write_connector_boundary_offset(path: Path) -> None:
    path.write_text(
        """<OpenDRIVE>
        <road id="1" junction="-1" length="10"><link><successor elementType="road" elementId="2" contactPoint="start"/></link>
          <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView></road>
        <road id="2" junction="7" length="10"><link/><planView><geometry s="0" x="13.5" y="0" hdg="0" length="10"><line/></geometry></planView></road>
        </OpenDRIVE>""",
        encoding="utf-8",
    )


def test_connector_offsets_are_diagnostic_by_default_but_gate_failures(tmp_path: Path):
    path = tmp_path / "offset.xodr"
    _write_connector_boundary_offset(path)
    diagnostic = check_geometric_continuity(str(path))
    gated = check_geometric_continuity(str(path), gate_junction_connectors=True)
    assert diagnostic["num_junction_connector_issues"] == 1
    assert diagnostic["ok"] is True
    assert gated["ok"] is False
    assert gated["gate_junction_connectors"] is True


def test_manager_scopes_connector_boundary_failures_to_explicit_gate(tmp_path: Path):
    """A legacy gate must not silently acquire a production-only failure."""
    path = tmp_path / "offset.xodr"
    _write_connector_boundary_offset(path)
    manager = QualityGateManager(ValidationReport(), logs_dir=str(tmp_path))

    legacy = manager.gate_geometric_continuity(str(path))

    assert legacy["ok"] is True
    assert legacy["num_junction_connector_issues"] == 1
    assert manager.get_failures() == {}
    assert (tmp_path / "geometric_continuity.json").is_file()

    production_candidate = manager.gate_junction_connector_boundary_alignment(
        str(path)
    )

    assert production_candidate["ok"] is False
    assert production_candidate["num_junction_connector_issues"] == 1
    assert set(manager.get_failures()) == {"junction_connector_boundary_alignment"}
    assert (tmp_path / "junction_connector_boundary_alignment.json").is_file()
