"""Q13 - Resource profiles without silent degradation.

The recorded GPU has 4 GB VRAM, so explicit governed profiles are defined.
A hardware-constrained profile must never be presented as equivalent to the
reference profile.
"""
from __future__ import annotations

from typing import Any, Dict, List

from phase_q.common import save_json, utcnow_iso

QUALITY_REFERENCE = "QUALITY_REFERENCE"
HARDWARE_CONSTRAINED = "HARDWARE_CONSTRAINED"
PERCEPTION_CAPTURE = "PERCEPTION_CAPTURE"
TRAFFIC_STRESS = "TRAFFIC_STRESS"

PROFILES: List[Dict[str, Any]] = [
    {
        "profile": QUALITY_REFERENCE,
        "resolution": [1920, 1080],
        "sensor_count": 6,
        "sensor_rates_hz": {"rgb": 30, "depth": 30, "semantic": 30,
                            "lidar": 20, "gnss": 10, "imu": 60},
        "quality_level": "High",
        "traffic_count": 80,
        "pedestrian_count": 60,
        "expected_fps": 25.0,
        "vram_gb": 4.0,
        "ram_gb": 16.0,
        "known_compromises": [],
        "note": "reference quality - do not equate other profiles with this",
    },
    {
        "profile": HARDWARE_CONSTRAINED,
        "resolution": [1280, 720],
        "sensor_count": 4,
        "sensor_rates_hz": {"rgb": 20, "semantic": 20, "lidar": 10, "gnss": 10},
        "quality_level": "Low",
        "traffic_count": 20,
        "pedestrian_count": 10,
        "expected_fps": 15.0,
        "vram_gb": 4.0,
        "ram_gb": 16.0,
        "known_compromises": ["reduced resolution", "reduced sensor rates",
                              "reduced traffic/pedestrians",
                              "must be reported as HARDWARE_CONSTRAINED, "
                              "never as equivalent to QUALITY_REFERENCE"],
    },
    {
        "profile": PERCEPTION_CAPTURE,
        "resolution": [1280, 720],
        "sensor_count": 6,
        "sensor_rates_hz": {"rgb": 30, "depth": 30, "semantic": 30,
                            "lidar": 20, "gnss": 10, "imu": 60},
        "quality_level": "Low",
        "traffic_count": 0,
        "pedestrian_count": 0,
        "expected_fps": 30.0,
        "vram_gb": 4.0,
        "ram_gb": 16.0,
        "known_compromises": ["no dynamic actors during capture",
                              "captures are perception-data focused"],
    },
    {
        "profile": TRAFFIC_STRESS,
        "resolution": [1280, 720],
        "sensor_count": 3,
        "sensor_rates_hz": {"rgb": 15, "lidar": 10, "gnss": 10},
        "quality_level": "Low",
        "traffic_count": 150,
        "pedestrian_count": 120,
        "expected_fps": 10.0,
        "vram_gb": 4.0,
        "ram_gb": 16.0,
        "known_compromises": ["low fps expected", "sensors reduced",
                              "stress results are not perception captures"],
    },
]


def profile_registry() -> Dict[str, Any]:
    return {
        "schema": "Q13_RESOURCE_PROFILES/v1",
        "governed_at": utcnow_iso(),
        "gpu": "NVIDIA Quadro P3200 with Max-Q Design",
        "vram_bytes": 4293918720,
        "profiles": PROFILES,
        "rule": "a HARDWARE_CONSTRAINED run must be labelled as such; "
                "it is never equivalent to QUALITY_REFERENCE",
    }