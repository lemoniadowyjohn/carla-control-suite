"""C11 reproducibility guards (digest-pinned inputs, PROJ environment).

Split out of ``ultimate_pipeline.governance`` so that the write-lock /
supervision plane lives in its own namespace (``governance.single_writer``)
and the deterministic-reproduction guards live in this one. The module paths
``ultimate_pipeline.governance.inputs_manifest`` and
``ultimate_pipeline.governance.proj_env_guard`` were moved here; see
``governance/__init__.py`` for the package map.

Submodules are intentionally NOT imported eagerly: ``proj_env_guard`` pulls
in ``pyproj``, which callers of ``inputs_manifest`` should not have to pay
for. Import the submodule you need.
"""
