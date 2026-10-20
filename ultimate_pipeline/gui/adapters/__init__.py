"""Mock backends, one per protocol in the Phase 1 foundation.

Split by service, mirroring ``09_ARCHITECTURE/SERVICES_AND_ADAPTER_CONTRACTS.md``:

* :mod:`~ultimate_pipeline.gui.adapters.mock_backend`      -- ``CarlaBackend``
* :mod:`~ultimate_pipeline.gui.adapters.mock_traffic`     -- ``TrafficManagerBackend``
* :mod:`~ultimate_pipeline.gui.adapters.mock_maps`        -- ``MapRegistryBackend``
* :mod:`~ultimate_pipeline.gui.adapters.mock_quality`     -- ``QualityGateBackend``
* :mod:`~ultimate_pipeline.gui.adapters.mock_calibration` -- ``CalibrationBackend``
* :mod:`~ultimate_pipeline.gui.adapters.mock_experiments` -- experiments / evidence / governance

Every mock is **deterministic** (seeded by construction, no ``random`` state
that varies between runs) and raises **no** import of ``carla`` at module
import time -- the simulator import is deliberately absent everywhere.

Every method returns a typed object (``Result`` / ``Tri`` /
``UnsupportedCapability``).  A mock never returns a bare ``None`` for an
operation that could have succeeded.
"""

__all__ = ["mock_backend", "mock_traffic", "mock_services", "build_mock_registry"]