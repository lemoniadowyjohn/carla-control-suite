"""Verify repository-owned Python namespaces import only from the expected source root.

Policy (fail-closed):
  * Repository-owned packages (e.g. ``ultimate_pipeline``) must resolve to the
    expected checkout root. Any resolution outside that root is rejected.
  * Third-party dependencies may legitimately come from site-packages and are
    not checked by this tool.
  * Missing repository-owned namespaces are reported as failures.

Usage::

    python tools/verify_import_authority.py [--expected-root /path/to/repo]

Exits 0 on PASS, non-zero on FAIL.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

#: Repository-owned top-level namespaces that must resolve from the expected root.
REPO_OWNED_NAMESPACES: frozenset[str] = frozenset({"ultimate_pipeline"})


def _expected_source_root() -> Path:
    """Default expected source root: the parent of the ``tools/`` directory."""
    return Path(__file__).resolve().parent.parent


def _is_within(path: Path, root: Path) -> bool:
    """True when ``path`` resolves to a location inside ``root``."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def verify_import_authority(
    expected_root: Path | None = None,
) -> dict[str, Any]:
    """Verify all repository-owned namespaces import from ``expected_root``.

    Returns a dict with ``schema``, ``expected_root``, ``passed`` and
    ``failures``. Exit code should be 0 when ``passed`` is True.
    """
    if expected_root is None:
        expected_root = _expected_source_root()
    expected_root = expected_root.resolve()

    failures: list[dict[str, Any]] = []

    for namespace in sorted(REPO_OWNED_NAMESPACES):
        try:
            module = importlib.import_module(namespace)
        except ImportError as exc:
            failures.append({
                "namespace": namespace,
                "status": "NOT_FOUND",
                "origin": None,
                "expected_root": str(expected_root),
                "message": (
                    f"repository-owned namespace {namespace!r} is not importable: {exc}"
                ),
            })
            continue

        origin = getattr(module, "__file__", None)
        if origin is None:
            failures.append({
                "namespace": namespace,
                "status": "NO_ORIGIN",
                "origin": None,
                "expected_root": str(expected_root),
                "message": (
                    f"namespace {namespace!r} has no __file__ origin "
                    f"(namespace package or built-in)"
                ),
            })
            continue

        origin_path = Path(origin)
        if not _is_within(origin_path, expected_root):
            failures.append({
                "namespace": namespace,
                "status": "WRONG_ORIGIN",
                "origin": str(origin),
                "expected_root": str(expected_root),
                "message": (
                    f"namespace {namespace!r} resolves to {origin}, "
                    f"outside expected root {expected_root}"
                ),
            })
            continue

    return {
        "schema": "import_authority/v1",
        "expected_root": str(expected_root),
        "passed": len(failures) == 0,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify repository-owned imports come from the expected source root."
    )
    parser.add_argument(
        "--expected-root",
        type=Path,
        default=None,
        help="Expected source root directory (default: parent of tools/)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON result",
    )
    args = parser.parse_args(argv)

    result = verify_import_authority(args.expected_root)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if result["passed"]:
            print(f"IMPORT_AUTHORITY PASS: all namespaces from {result['expected_root']}")
        else:
            print(f"IMPORT_AUTHORITY FAIL: expected root {result['expected_root']}")
            for f in result["failures"]:
                print(f"  {f['namespace']}: {f['message']}")

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
