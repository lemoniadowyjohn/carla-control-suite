import xml.etree.ElementTree as ET
from ultimate_pipeline.tiling.tile_extractor import _analyze_tile_lanes

def test_lane_successor_leakage():
    tile_root = ET.fromstring("""
    <OpenDRIVE>
      <road id="1">
        <lanes>
          <laneSection>
            <lane id="1" type="driving" was_driving="true">
              <link>
                <successor road="99"/>
              </link>
            </lane>
          </laneSection>
        </lanes>
      </road>
    </OpenDRIVE>
    """)

    result = _analyze_tile_lanes(tile_root, preserve_global=True)

    assert result["driving_like"] == 1
    assert result["successor_outside"] == 1
    assert result["predecessor_outside"] == 0
