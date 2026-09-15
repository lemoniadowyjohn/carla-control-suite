"""Warning taxonomy tests (Task 3)."""
import sys
sys.path.insert(0, '.')

from ultimate_pipeline.contracts.stage_contracts import (
    WarningDefinition, warning, register_warning, lookup_warning,
    QualityStatus, WARNING_REGISTRY
)


def test_warning_definition():
    """Test WarningDefinition dataclass."""
    w = WarningDefinition(
        code="GEOM-001",
        domain="geometry",
        severity="error",
        release_impact="FAIL",
        waiver_allowed=False,
    )
    assert w.code == "GEOM-001"
    assert w.domain == "geometry"
    assert w.severity == "error"
    assert w.release_impact == "FAIL"
    assert w.waiver_allowed == False
    print('PASS: test_warning_definition')


def test_warning_factory():
    """Test warning factory function."""
    w = warning("TOPO-001", "topology", severity="warning", release_impact="INCOMPLETE", waiver_allowed=True)
    assert w.code == "TOPO-001"
    assert w.domain == "topology"
    assert w.severity == "warning"
    assert w.release_impact == "INCOMPLETE"
    assert w.waiver_allowed == True
    print('PASS: test_warning_factory')


def test_warning_registry():
    """Test that pre-registered warnings exist in the registry."""
    # Check that our pre-registered warnings are in the registry
    codes = [defn.code for defn in WARNING_REGISTRY.keys()]
    assert "GEOM-001" in codes
    assert "TOPO-001" in codes
    assert "LANE-001" in codes
    assert "DEM-001" in codes
    assert "CARLA-001" in codes
    print('PASS: test_warning_registry')


def test_lookup_warning():
    """Test looking up a warning by code."""
    w = lookup_warning("GEOM-001")
    assert w is not None
    assert w.code == "GEOM-001"
    
    w = lookup_warning("UNKNOWN-999")
    assert w is None
    print('PASS: test_lookup_warning')


def test_register_warning():
    """Test registering a new warning."""
    new_w = warning("CUSTOM-001", "custom", severity="info", release_impact="NONE", waiver_allowed=False)
    register_warning(new_w, "waiver-123")
    assert "CUSTOM-001" in [defn.code for defn in WARNING_REGISTRY.keys()]
    print('PASS: test_register_warning')


if __name__ == '__main__':
    test_warning_definition()
    test_warning_factory()
    test_warning_registry()
    test_lookup_warning()
    test_register_warning()
    print()
    print('All Task 3 tests PASSED!')