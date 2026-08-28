import os
os.environ["OD_SMOOTH_JUNCTIONS"] = "0"
os.environ["OD_VERTEX_DISTANCE"] = "10.0"
os.environ["WINDOW_S"] = "5400"
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))
import scripts.opendrive_smooth_test as t

# override XODR to the governed full file
t.GOVERNED_XODR = Path("campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr")
t.VERTEX = 10.0
t.SMOOTH = False
t.PROGRESS.parent = Path("reports/post_audit_hardening/_gen_watch_log")
t.PROGRESS = t.PROGRESS.parent / "full_v10_progress.log"
import asyncio  # noqa
raise SystemExit(t.main())
