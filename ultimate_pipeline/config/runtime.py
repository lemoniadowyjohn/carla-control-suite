"""
Runtime Configuration Flags

This file defines global runtime switches controlling heavy dependencies
such as CARLA. It exists to prevent accidental simulator crashes and to
enable headless execution on clusters.
"""

# --------------------------------------------------
# CARLA Controls
# --------------------------------------------------
ENABLE_CARLA = False
ENABLE_CARLA_QA = False
ENABLE_TILE_STREAMING = False

# --------------------------------------------------
# Safety & Debugging
# --------------------------------------------------
FAIL_FAST_ON_CARLA_ERROR = False
LOG_CARLA_RESTARTS = True

# --------------------------------------------------
# Research Modes
# --------------------------------------------------
DETERMINISTIC_MODE = True
ALLOW_RANDOMIZED_MAPS = True
