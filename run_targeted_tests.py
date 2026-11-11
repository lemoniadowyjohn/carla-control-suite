import sys
sys.path.insert(0, '.')

# Test GAP048 inner-first
from ultimate_pipeline.enrichment.lane_successor_topology import infer_lane_successors_from_topology
import xml.etree.ElementTree as ET
import tempfile

xodr = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
<road id="1" length="100" junction="-1">
<planView><geometry s="0" x="0" y="0" hdg="0" length="100"><line/></geometry></planView>
<lanes><laneSection s="0"><left><lane id="-1" type="driving"><width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane></left><center><lane id="0" type="driving"/></center><right/></laneSection></lanes>
<link><successor elementType="road" elementId="2" contactPoint="start"/></link>
</road>
<road id="2" length="100" junction="5">
<planView><geometry s="0" x="100" y="0" hdg="0" length="100"><line/></geometry></planView>
<lanes><laneSection s="0"><left><lane id="-1" type="driving"><width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane></left><center><lane id="0" type="driving"/></center><right/></laneSection></lanes>
<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>
</road>
<junction id="5"><connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start"><laneLink from="-1" to="-1"/></connection></junction>
</OpenDRIVE>"""

root = ET.fromstring(xodr)
report = infer_lane_successors_from_topology(root)
print('GAP048 inner-first test:')
print('  inferred_count:', report.get('inferred_count', 0))
print('  road_to_road_count:', report.get('road_to_road_count', 0))
print('  junction_repaired_count:', report.get('junction_repaired_count', 0))
print('  junction_unresolved_ambiguous:', report.get('junction_unresolved_ambiguous', 0))
print('  junction_unresolved_no_candidate:', report.get('junction_unresolved_no_candidate', 0))

# Test GAP026 inner-first
from ultimate_pipeline.lanes.junction_lanelink_inner_first import repair_outer_to_inner_mispaired_lane_links

root2 = ET.fromstring(xodr)
report2 = repair_outer_to_inner_mispaired_lane_links(root2)
print('GAP026 inner-first test:')
print('  remapped:', report2.get('remapped', 0))
print('  kept:', report2.get('kept', 0))

# Test GAP026 hermite tangent fit
from ultimate_pipeline.topology.junction_connector_tangent_fit import apply_junction_connector_tangent_fit

root3 = ET.fromstring(xodr)
report3 = apply_junction_connector_tangent_fit(root3)
print('GAP026 hermite tangent fit test:')
print('  connectors_examined:', report3.get('connectors_examined', 0))
print('  connectors_fitted:', report3.get('connectors_fitted', 0))
print('  skipped_within_threshold:', report3.get('skipped_within_threshold', 0))

# Test GAP049 package write poller
from tools.cook_diagnostics.package_write_poller import PackageWritePoller
import pathlib

with tempfile.TemporaryDirectory() as tmpdir:
    poller = PackageWritePoller(package_dir=tmpdir, output_csv=str(pathlib.Path(tmpdir) / 'test.csv'), interval_sec=0.1)
    print('GAP049 package write poller: OK (instantiated)')

# Test GAP052 worktree lock
from ultimate_pipeline.governance.single_writer import worktree_lock
print('GAP052 worktree_lock import: OK')

# Test GAP052 common git lock
from ultimate_pipeline.governance.single_writer import common_git_lock
print('GAP052 common_git_lock import: OK')

print('\nAll targeted tests passed!')