from pathlib import Path

from ultimate_pipeline.quality.check_geometric_continuity import check_geometric_continuity


def test_connector_offsets_are_diagnostic_by_default_but_gate_failures(tmp_path: Path):
    path = tmp_path / "offset.xodr"
    path.write_text(
        """<OpenDRIVE>
        <road id="1" junction="-1" length="10"><link><successor elementType="road" elementId="2" contactPoint="start"/></link>
          <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView></road>
        <road id="2" junction="7" length="10"><link/><planView><geometry s="0" x="13.5" y="0" hdg="0" length="10"><line/></geometry></planView></road>
        </OpenDRIVE>""",
        encoding="utf-8",
    )
    diagnostic = check_geometric_continuity(str(path))
    gated = check_geometric_continuity(str(path), gate_junction_connectors=True)
    assert diagnostic["num_junction_connector_issues"] == 1
    assert diagnostic["ok"] is True
    assert gated["ok"] is False
    assert gated["gate_junction_connectors"] is True
