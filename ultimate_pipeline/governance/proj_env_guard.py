"""C11 (HIGH) — PROJ environment startup guard.

A stale or foreign ``proj.db`` is a latent *silent* reprojection risk: CRS
transforms (WGS84 <-> UTM32N, DEM <-> XODR, etc.) can quietly produce wrong
coordinates instead of raising, because PROJ generally degrades gracefully
rather than erroring on an old/partial database. Two independent risks are
checked here:

1. **Old database layout.** ``proj.db``'s own metadata records
   ``DATABASE.LAYOUT.VERSION.MAJOR``/``MINOR``. A minor version below the
   version pyproj/PROJ were built against ("from another PROJ installation")
   means some transforms/records the running PROJ expects may be missing or
   shaped differently than the code was validated against.
2. **Foreign PROJ_LIB/PROJ_DATA env var.** These env vars tell (some, not
   all) PROJ-consuming libraries where to load proj.db from. If the value
   present in the environment does not match the data dir pyproj itself
   would resolve, some other component (a different venv's GDAL, a system
   PROJ install, ...) may end up using a different, unvetted proj.db than
   the one this repo's transforms were validated against.

This module only *detects and reports*; the actual environment repair
(pinning pyproj/GDAL to a consistent proj.db, e.g. via
``python -m pip install --force-reinstall pyproj`` in a clean venv, or
unsetting a stray system-wide ``PROJ_LIB``) is an operator step documented in
``reports/post_audit_hardening/C11_REPRODUCIBILITY.md``.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


class ProjEnvironmentError(Exception):
    """Raised by check_proj_environment(fail_closed=True) when the PROJ
    environment does not meet the minimum requirement."""


@dataclass
class ProjEnvironmentReport:
    ok: bool
    data_dir: str
    proj_db_path: str
    proj_db_layout_version: Optional[float]
    pyproj_version: Optional[str]
    warnings: List[str] = field(default_factory=list)


def _read_proj_db_layout_version(proj_db_path: Path) -> Optional[float]:
    """Read DATABASE.LAYOUT.VERSION.MAJOR/MINOR from proj.db's metadata table.

    Returns the minor version as a float (e.g. 4.0), or None if it cannot be
    determined (missing file, unexpected schema, etc.) -- callers treat None
    as "unknown", not as a pass.
    """
    if not proj_db_path.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{proj_db_path}?mode=ro", uri=True)
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT value FROM metadata WHERE key = 'DATABASE.LAYOUT.VERSION.MINOR'"
            )
            row = cur.fetchone()
            if row is None:
                return None
            return float(row[0])
        finally:
            con.close()
    except Exception:
        return None


def check_proj_environment(
    *,
    min_layout_minor: int = 6,
    fail_closed: bool = False,
) -> ProjEnvironmentReport:
    """Check the PROJ/pyproj environment for reproducibility risks.

    Args:
        min_layout_minor: minimum acceptable proj.db
            DATABASE.LAYOUT.VERSION.MINOR. The spec's confirmed-bad reading
            is 4; PROJ installs built against newer proj-data expect >= 6.
        fail_closed: if True, raise ProjEnvironmentError when the report is
            not ok. If False (default), return the report with warnings
            populated and let the caller decide (loud-warn mode).

    Returns:
        A ProjEnvironmentReport. ``ok`` is False iff the resolved proj.db's
        layout minor version is known and below ``min_layout_minor``.
        Foreign PROJ_LIB/PROJ_DATA env vars are always reported as warnings
        but do not by themselves flip ``ok`` to False (pyproj may correctly
        ignore them and resolve its own bundled data dir; the risk is for
        *other* PROJ-consuming components in the same process/environment).
    """
    warnings: List[str] = []

    try:
        import pyproj
        from pyproj import datadir as pyproj_datadir

        pyproj_version: Optional[str] = pyproj.__version__
        data_dir = pyproj_datadir.get_data_dir()
    except Exception as exc:  # pragma: no cover - pyproj is a hard dependency here
        warnings.append(f"pyproj unavailable/unimportable: {exc!r}")
        report = ProjEnvironmentReport(
            ok=False,
            data_dir="",
            proj_db_path="",
            proj_db_layout_version=None,
            pyproj_version=None,
            warnings=warnings,
        )
        if fail_closed:
            raise ProjEnvironmentError(
                "PROJ environment check failed: pyproj is unavailable. "
                f"warnings={warnings}"
            )
        return report

    proj_db_path = Path(data_dir) / "proj.db"
    layout_minor = _read_proj_db_layout_version(proj_db_path)

    ok = True
    if layout_minor is None:
        warnings.append(
            f"Could not determine proj.db DATABASE.LAYOUT.VERSION.MINOR at "
            f"{proj_db_path}; unable to verify PROJ database compatibility."
        )
    elif layout_minor < min_layout_minor:
        ok = False
        warnings.append(
            f"proj.db DATABASE.LAYOUT.VERSION.MINOR={layout_minor:g} at {proj_db_path} "
            f"is older than the required minimum ({min_layout_minor}). This is a "
            "silent-reprojection risk: CRS transforms may use a stale/incomplete "
            "database instead of raising. Remediation: reinstall pyproj so its "
            "bundled proj.db is refreshed (e.g. "
            "`pip install --force-reinstall --no-cache-dir pyproj` in this venv), "
            "or align GDAL's PROJ data with pyproj's via a consistent conda/pip "
            "environment (do not mix a system PROJ install with pyproj's bundled one)."
        )

    for env_key in ("PROJ_LIB", "PROJ_DATA"):
        env_val = os.environ.get(env_key)
        if not env_val:
            continue
        try:
            same = Path(env_val).resolve() == Path(data_dir).resolve()
        except Exception:
            same = False
        if not same:
            warnings.append(
                f"{env_key}={env_val!r} does not match pyproj's own resolved data "
                f"dir ({data_dir!r}). This is the 'from another PROJ installation' "
                "risk: any PROJ-consuming component that honors this env var "
                "(GDAL, a raw libproj binding, etc.) may load a different, "
                f"unvetted proj.db than pyproj itself uses. Remediation: unset "
                f"{env_key}, or point it at pyproj's own data dir."
            )

    report = ProjEnvironmentReport(
        ok=ok,
        data_dir=str(data_dir),
        proj_db_path=str(proj_db_path),
        proj_db_layout_version=layout_minor,
        pyproj_version=pyproj_version,
        warnings=warnings,
    )

    if fail_closed and not ok:
        raise ProjEnvironmentError(
            "PROJ environment check failed (fail_closed=True): " + "; ".join(warnings)
        )

    return report
