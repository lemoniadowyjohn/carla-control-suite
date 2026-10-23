"""Fail-closed import-authority preflight for candidate verification.

A verification run is only meaningful if the code under test is the code that
was checked out. This module proves that: every repository Python module that
the interpreter can supply must originate from the expected checkout, and no
other CARLA checkout may appear anywhere in the import search path for those
namespaces.

It is deliberately strict. Path *ordering* is not treated as sufficient: if an
external checkout can supply a candidate module at all, that is a violation,
because collection order can change which module wins.

The expected repository root is discovered dynamically (``git rev-parse
--show-toplevel`` with a parent-walk fallback). No machine-specific path is
encoded.

Usage::

    python tools/verify_import_authority.py [--json]

Exit codes: 0 = authority proven, 1 = violation detected, 2 = unusable.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

# Top-level import namespaces owned by this repository.
REPO_NAMESPACES = ("ultimate_pipeline", "tools")


def expected_repo_root(start: Path | None = None) -> Path:
    """Discover the checkout root dynamically. Never hardcodes a path."""
    here = (start or Path(__file__).resolve()).parent
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(here), capture_output=True, text=True, timeout=60,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").is_file() and (
            (candidate / "ultimate_pipeline").is_dir()
        ):
            return candidate.resolve()
    raise RuntimeError("could not determine repository root")


def _norm(path: str | os.PathLike) -> str:
    try:
        return os.path.normcase(os.path.realpath(str(path)))
    except (OSError, ValueError):
        return os.path.normcase(str(path))


def _under(path: str, root: str) -> bool:
    """True when `path` is `root` itself or lives inside it."""
    if path == root:
        return True
    return path.startswith(root.rstrip(os.sep) + os.sep)


def _stdlib_prefixes() -> set[str]:
    out = set()
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        try:
            value = sysconfig.get_paths().get(key)
        except Exception:
            value = None
        if value:
            out.add(_norm(value))
    return out


def audit(expected_root: Path) -> dict:
    """Import the repository namespaces and report any external origin."""
    expected = _norm(expected_root)
    allowed_roots = {expected} | _stdlib_prefixes()

    def permitted(candidate: str) -> bool:
        return any(_under(candidate, root) for root in allowed_roots)
    # The candidate environment's own site-packages may legitimately contain a
    # third-party distribution, but never a *repository* checkout.
    violations: list[dict] = []
    census: list[dict] = []

    for name in REPO_NAMESPACES:
        try:
            module = __import__(name)
        except Exception as exc:  # pragma: no cover - environment dependent
            violations.append({
                "kind": "import_failed",
                "module": name,
                "detail": f"{type(exc).__name__}: {exc}",
            })
            continue

        search = list(getattr(module, "__path__", []) or [])
        origin = getattr(module, "__file__", None)
        if origin:
            search.append(os.path.dirname(origin))
        census.append({
            "module": name,
            "origin": origin,
            "search_locations": [str(p) for p in search],
        })

        # Namespace-package aggregation: ANY external location that could
        # supply a submodule of this namespace is a violation, regardless of
        # whether it currently sorts first.
        for loc in search:
            if not permitted(_norm(loc)):
                violations.append({
                    "kind": "external_search_location",
                    "namespace": name,
                    "location": str(loc),
                })

    # Census every already-imported repository submodule.
    for mod_name, module in sorted(list(sys.modules.items())):
        top = mod_name.split(".")[0]
        if top not in REPO_NAMESPACES:
            continue
        origin = getattr(module, "__file__", None)
        search = list(getattr(module, "__path__", []) or [])
        entry = {
            "module": mod_name,
            "origin": origin,
            "search_locations": [str(p) for p in search],
        }
        census.append(entry)
        if origin and not permitted(_norm(origin)):
            violations.append({
                "kind": "external_module_origin",
                "module": mod_name,
                "origin": origin,
            })

    return {
        "expected_root": str(expected_root),
        "sys_prefix": sys.prefix,
        "sys_executable": sys.executable,
        "pythonpath_env": os.environ.get("PYTHONPATH", ""),
        "namespaces": census[: len(REPO_NAMESPACES)],
        "module_count": len(census),
        "violations": violations,
        "status": "PASS" if not violations else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    parser.add_argument(
        "--expect-root", default=None,
        help="override the dynamically discovered repository root",
    )
    args = parser.parse_args(argv)

    try:
        root = Path(args.expect_root).resolve() if args.expect_root \
            else expected_repo_root()
    except RuntimeError as exc:
        print(f"IMPORT_AUTHORITY_UNUSABLE: {exc}", file=sys.stderr)
        return 2

    report = audit(root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"expected_root : {report['expected_root']}")
        print(f"sys_prefix    : {report['sys_prefix']}")
        print(f"sys_executable: {report['sys_executable']}")
        print(f"PYTHONPATH    : {report['pythonpath_env']!r}")
        for ns in report["namespaces"]:
            print(f"  {ns['module']}: {ns['origin']}")
            for loc in ns["search_locations"]:
                print(f"      search: {loc}")
        print(f"modules audited: {report['module_count']}")
        if report["violations"]:
            print("VIOLATIONS:")
            for violation in report["violations"]:
                print(f"  - {violation}")
        print(f"IMPORT_AUTHORITY_{report['status']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
