
import pytest
import xml.etree.ElementTree as ET
from ultimate_pipeline.geometry.geometry_math import sample_parampoly3_points
import math

def test_parampoly3_non_finite_coefficients():
    geom = ET.Element("geometry")
    pp = ET.SubElement(geom, "paramPoly3", attrib={"aU": "inf", "bU": "1.0"})
    
    try:
        sample_parampoly3_points(geom, 0.0, 0.0, 0.0, 10.0, [0.0, 1.0])
    except ValueError as e:
        print(f"DEBUG: Caught expected error: {e}")
        assert "Non-finite coefficient found" in str(e)
    except Exception as e:
        pytest.fail(f"Caught unexpected exception: {type(e).__name__}: {e}")
    else:
        pytest.fail("Did not raise ValueError")

def test_parampoly3_non_positive_length():
    geom = ET.Element("geometry")
    ET.SubElement(geom, "paramPoly3", attrib={"aU": "0.0", "bU": "1.0"})
    
    with pytest.raises(ValueError, match="Geometry length must be positive"):
        sample_parampoly3_points(geom, 0.0, 0.0, 0.0, 0.0, [0.0, 1.0])

def test_parampoly3_sampling_monotonicity():
    geom = ET.Element("geometry")
    ET.SubElement(geom, "paramPoly3", attrib={"aU": "0.0", "bU": "1.0"})
    
    # Passing unsorted and duplicate parameters
    points = sample_parampoly3_points(geom, 0.0, 0.0, 0.0, 10.0, [0.5, 0.1, 0.5, 0.9])
    
    # Should be sorted and unique
    assert len(points) == 3
    # Check if they are sorted
    # (The actual values depend on the math, but the number of points should be 3 if uniqueness is enforced)
    # With t=[0.1, 0.5, 0.9], p=[1.0, 5.0, 9.0], u=[1.0, 5.0, 9.0], v=[0,0,0], 
    # points = [(1, 0), (5, 0), (9, 0)]
    assert points == [(1.0, 0.0), (5.0, 0.0), (9.0, 0.0)]
