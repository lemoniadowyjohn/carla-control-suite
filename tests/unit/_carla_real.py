"""Helper for tests that are only meaningful against the real CARLA PythonAPI.

``tests/unit/conftest.py`` (and ``tests/unit/test_batch1_cd1_cd4_contracts.py``)
install a minimal offline ``carla`` stub into ``sys.modules`` when the real
client is not importable, so that the rest of the offline suite can import
``carla`` without erroring. That stub is marked with ``__offline_stub__ =
True``.

A plain ``pytest.importorskip("carla")`` therefore does NOT skip on a
carla-less machine once that stub is installed: the import succeeds (it
imports the stub), so the test runs against the stub's fake attributes
instead of being skipped, and fails with a confusing error instead of a
clean SKIP.

``require_real_carla()`` is the fix: it imports (or skips if unimportable,
exactly like ``importorskip``) and then additionally skips if the imported
module is the offline stub, so a test meant to validate behaviour against
the genuine live-client API gets a clean, honest SKIP on a carla-less
machine and only actually runs when the real client is present.
"""

from __future__ import annotations

import pytest


def require_real_carla():
    """Return the real ``carla`` module, or skip the test.

    Skips (does not fail) when:
    - ``carla`` cannot be imported at all, or
    - ``carla`` imports successfully but is the offline stub installed by
      ``tests/unit/conftest.py`` / ``tests/unit/test_batch1_cd1_cd4_contracts.py``.
    """
    carla = pytest.importorskip("carla")
    if getattr(carla, "__offline_stub__", False):
        # allow_module_level=True so this also works as a module-level guard
        # (e.g. a whole test module that only makes sense against the real
        # client); it is a no-op when called inside a test function.
        pytest.skip(
            "real carla client not available; only the offline stub is importable",
            allow_module_level=True,
        )
    return carla
