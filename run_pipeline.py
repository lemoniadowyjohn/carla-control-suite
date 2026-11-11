#!/usr/bin/env python3
import os
import sys

# Set environment variables
os.environ['UP_INPUT_XODR'] = 'campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr'
os.environ['UP_DISABLE_CARLA'] = '1'
os.environ['ENABLE_CARLA_TEST_EARLY'] = '0'
os.environ['ENABLE_CARLA_ELEVATION_VALIDATION'] = '0'
os.environ['FORCE_LIGHT_LOAD_IN_STEP_8'] = '1'

# Import and run pipeline
from ultimate_pipeline.cli import pipeline_run

# Call the pipeline
try:
    pipeline_run(())
except SystemExit as e:
    print(f"Pipeline exited with code: {e.code}")
except Exception as e:
    print(f"Pipeline error: {e}")
    import traceback
    traceback.print_exc()