#!/usr/bin/env python3
import os
os.environ['UP_AUTOFIX_LANE_SUCCESSORS'] = '1'

from ultimate_pipeline.quality.check_lane_connectivity import autofix_missing_lane_successors
from pathlib import Path

xodr_path = Path(r'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\stage8_rca_output\08_final_laneSectionFixed.xodr')
output_path = Path(r'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\stage8_rca_output\08_final_laneSectionFixed_lane_successor_fixed2.xodr')

print('Running autofix...')
report = autofix_missing_lane_successors(xodr_path, allow_dead_ends=True, output_path=output_path)
print(f'Broken before: {report["broken_before_count"]}')
print(f'Fixed: {report["fixed_count"]}')
print(f'Still broken: {report["still_broken_count"]}')
print(f'Output: {report["output_xodr"]}')

# Verify the output
from ultimate_pipeline.quality.check_lane_connectivity import assert_all_lanes_have_successors
try:
    assert_all_lanes_have_successors(output_path, allow_dead_ends=True)
    print("✅ Re-check PASSED")
except RuntimeError as e:
    print(f"❌ Re-check FAILED: {e}")