"""Test the XODR schema validator."""
from ultimate_pipeline.quality.xodr_schema_validator import validate_xodr_schema
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
import os

# Create a minimal valid XODR for testing
root = ET.Element('OpenDRIVE')
header = ET.SubElement(root, 'header')
geo = ET.SubElement(header, 'geoReference')
geo.text = 'UTM 32N 500000 5000000'
ET.SubElement(header, 'offset', x='0', y='0', z='0', hdg='0')

road = ET.SubElement(root, 'road', id='1', length='100.0')
plan_view = ET.SubElement(road, 'planView')
geom = ET.SubElement(plan_view, 'geometry', s='0', length='100.0', x='0', y='0', hdg='0')

tree = ET.ElementTree(root)

with tempfile.NamedTemporaryFile(suffix='.xodr', delete=False, mode='w') as f:
    tree.write(f, encoding='unicode', xml_declaration=False)
    tmp_path = f.name

result = validate_xodr_schema(Path(tmp_path))
print(f'Valid XODR result: {result}')

# Test with invalid XODR (wrong root tag)
root2 = ET.Element('WrongTag')
tree2 = ET.ElementTree(root2)
with tempfile.NamedTemporaryFile(suffix='.xodr', delete=False, mode='w') as f:
    tree2.write(f, encoding='unicode', xml_declaration=False)
    tmp_path2 = f.name

result2 = validate_xodr_schema(Path(tmp_path2))
print(f'Invalid XODR result: {result2}')

os.unlink(tmp_path)
os.unlink(tmp_path2)

print('All validator tests passed!')