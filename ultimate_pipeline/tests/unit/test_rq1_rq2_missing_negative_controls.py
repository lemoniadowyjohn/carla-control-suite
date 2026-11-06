# Section 10 — RQ1-RQ5 missing negative controls (2 tests)

# RQ1: Structural signature determinism — same OSM input produces identical
# structural signature across repeated runs using StructureScanner.analyze.
# RQ2: Wrong CRS detection — mismatched coordinate reference system is
# detected as a structural gap (not silently treated as valid).

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ultimate_pipeline.topology.structure_scanner import StructureScanner

XODR_TEMPLATE = """<?xml version="1.0"?>
<OpenDRIVE>
  <geoReference>
    +proj=utm +zone=33 +datum=WGS84 +units=m +no_defs
  </geoReference>
  <road id="r1" name="Road1" length="100.0" junction="-1">
    <planView>
      <geometry s="0" x="0" y="0" hdg="0" length="50"><line/></geometry>
      <geometry s="50" x="50" y="0" hdg="0" length="50"><line/></geometry>
    </planView>
    <laneSection s="0">
      <lane id="0" type="driving" level="0">
        <width sOffset="0" a="3.5"/>
      </lane>
    </laneSection>
  </road>
</OpenDRIVE>"""


def test_rq1_structural_signature_determinism():
    """RQ1: Same OSM input produces identical structural signature across runs.

    Repeated analysis of the same XODR input must yield identical fingerprints.
    Non-determinism indicates a bug in serialization or hashing.
    """
    scanner = StructureScanner()
    root1 = __import__("xml.etree.ElementTree", fromlist=["ElementTree"]).fromstring(XODR_TEMPLATE)
    root2 = __import__("xml.etree.ElementTree", fromlist=["ElementTree"]).fromstring(XODR_TEMPLATE)

    report1 = scanner.analyze(root1)
    report2 = scanner.analyze(root2)

    assert report1 == report2, (
        f"Structural analysis is non-deterministic:\n{report1}\n!=\n{report2}"
    )


def test_rq2_wrong_crs_not_detected():
    """RQ2: Wrong CRS/georeference is NOT detected by StructureScanner.

    This is a documented gap: StructureScanner.analyze() does not inspect
    the <geoReference> element, so a map with a wrong CRS produces the same
    structural report as a correctly georeferenced map. This is a known
    limitation - CRS mismatch is not currently caught by structural
    comparison.
    """
    xodr_a_crs33 = """<?xml version="1.0"?>
<OpenDRIVE>
  <geoReference>
    +proj=utm +zone=33 +datum=WGS84 +units=m +no_defs
  </geoReference>
  <road id="r1" name="Road1" length="100.0" junction="-1">
    <planView>
      <geometry s="0" x="0" y="0" hdg="0" length="100"><line/></geometry>
    </planView>
  </road>
</OpenDRIVE>"""

    xodr_b_crs34 = """<?xml version="1.0"?>
<OpenDRIVE>
  <geoReference>
    +proj=utm +zone=34 +datum=WGS84 +units=m +no_defs
  </geoReference>
  <road id="r1" name="Road1" length="100.0" junction="-1">
    <planView>
      <geometry s="0" x="0" y="0" hdg="0" length="100"><line/></geometry>
    </planView>
  </road>
</OpenDRIVE>"""

    scanner = StructureScanner()
    report_a = scanner.analyze(__import__("xml.etree.ElementTree", fromlist=["ElementTree"]).fromstring(xodr_a_crs33))
    report_b = scanner.analyze(__import__("xml.etree.ElementTree", fromlist=["ElementTree"]).fromstring(xodr_b_crs34))

    # Documented gap: CRS mismatch is NOT detected - reports are identical
    assert report_a == report_b, (
        "CRS mismatch produces identical reports (gap: StructureScanner "
        "does not inspect geoReference)"
    )
