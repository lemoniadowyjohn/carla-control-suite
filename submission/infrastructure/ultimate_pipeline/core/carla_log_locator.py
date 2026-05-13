from __future__ import annotations
import os
from typing import Optional

def locate_carla_log_path(settings=None, out_dir: Optional[str]=None) -> Optional[str]:
    """Best-effort CARLA server log discovery on Windows/Linux."""
    if settings is not None:
        p = getattr(settings, "CARLA_SERVER_LOG", None)
        if p and os.path.exists(p):
            return p

    if out_dir:
        p2 = os.path.join(out_dir, "logs", "carla_server.log")
        if os.path.exists(p2):
            return p2

    la = os.environ.get("LOCALAPPDATA")
    if la:
        p3 = os.path.join(la, "CarlaUE4", "Saved", "Logs", "CarlaUE4.log")
        if os.path.exists(p3):
            return p3

    cr = os.environ.get("CARLA_ROOT") or os.environ.get("CARLA_HOME")
    if cr:
        p4 = os.path.join(cr, "CarlaUE4", "Saved", "Logs", "CarlaUE4.log")
        if os.path.exists(p4):
            return p4

    return None
