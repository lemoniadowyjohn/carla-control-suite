#!/usr/bin/env python3
"""Recursive directory hashing tool for thesis reproducibility.

Provides stable, reproducible hashing of all files in a directory tree,
with configurable ignore patterns. Output is JSON for easy diff and storage.

Usage:
    python -m ultimate_pipeline.tools.hash_tree --in DIR --out hashes.json --algo sha256
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

# Default patterns to ignore (similar to determinism audit)
DEFAULT_IGNORE_PATTERNS: List[str] = [
    # Log and temporary files
    "*.log",
    "*.tmp",
    "*.cache",
    # Python artifacts
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
    "*.egg-info",
    # Version control
    ".git",
    ".gitignore",
    ".gitattributes",
    # IDE artifacts
    ".idea",
    ".vscode",
    "*.swp",
    "*.swo",
    # Build artifacts
    "*.o",
    "*.obj",
    "*.so",
    "*.dll",
    # Crash and error artifacts
    "crash_traceback.txt",
    "crash_summary.json",
    # Database files (often contain timestamps)
    "*.sqlite",
    "*.db",
    # Settings snapshots (contain timestamps)
    "settings_snapshot.json",
    "domain_gap_settings_snapshot.json",
]


def _matches_pattern(name: str, pattern: str) -> bool:
    """Check if a filename matches a glob-like pattern.

    Supports:
    - Exact match: "foo.log" matches "foo.log"
    - Wildcard prefix: "*.log" matches "foo.log"
    - Exact directory match: "__pycache__" matches directory name
    """
    if pattern.startswith("*."):
        # Extension match
        suffix = pattern[1:]  # ".log"
        return name.endswith(suffix)
    else:
        # Exact match
        return name == pattern


def _should_ignore(path: Path, ignore_patterns: List[str]) -> bool:
    """Check if a path should be ignored based on patterns."""
    # Check the filename itself
    name = path.name
    for pattern in ignore_patterns:
        if _matches_pattern(name, pattern):
            return True

    # Check if any parent directory matches
    for part in path.parts:
        for pattern in ignore_patterns:
            if _matches_pattern(part, pattern):
                return True

    return False


def _hash_file(path: Path, algo: str) -> str:
    """Hash a file using the specified algorithm."""
    h = hashlib.new(algo)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_tree(
    root: str,
    algo: str = "sha256",
    ignore: Optional[List[str]] = None,
) -> Dict[str, any]:
    """Recursively hash all files in a directory tree.

    Args:
        root: Root directory to hash.
        algo: Hash algorithm (e.g., "sha256", "md5").
        ignore: List of patterns to ignore. If None, uses DEFAULT_IGNORE_PATTERNS.

    Returns:
        Dictionary with structure:
        {
            "root": "/absolute/path/to/root",
            "algo": "sha256",
            "files": {
                "relative/path/file1": "hash...",
                "relative/path/file2": "hash...",
            }
        }

    Raises:
        ValueError: If root does not exist or is not a directory.
        ValueError: If algo is not supported.
    """
    root_path = Path(root).expanduser().resolve()

    if not root_path.exists():
        raise ValueError(f"Root directory does not exist: {root_path}")
    if not root_path.is_dir():
        raise ValueError(f"Root is not a directory: {root_path}")

    # Validate algorithm
    try:
        hashlib.new(algo)
    except ValueError as e:
        raise ValueError(f"Unsupported hash algorithm '{algo}': {e}") from e

    if ignore is None:
        ignore = DEFAULT_IGNORE_PATTERNS

    files_hashes: Dict[str, str] = {}
    ignored_count = 0

    # Walk directory tree in sorted order for reproducibility
    all_files: List[Path] = sorted(root_path.rglob("*"))

    for file_path in all_files:
        if not file_path.is_file():
            continue

        # Get relative path for checking and output
        rel_path = file_path.relative_to(root_path)
        rel_str = str(rel_path).replace("\\", "/")  # Normalize for cross-platform

        if _should_ignore(rel_path, ignore):
            ignored_count += 1
            continue

        try:
            file_hash = _hash_file(file_path, algo)
            files_hashes[rel_str] = file_hash
        except (OSError, IOError) as e:
            # Skip files we can't read (permissions, etc.)
            print(f"Warning: Could not hash {rel_str}: {e}", file=sys.stderr)
            continue

    return {
        "root": str(root_path),
        "algo": algo,
        "files": files_hashes,
        "_meta": {
            "file_count": len(files_hashes),
            "ignored_count": ignored_count,
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(
        description="Recursively hash all files in a directory tree",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m ultimate_pipeline.tools.hash_tree --in ./output --out hashes.json
    python -m ultimate_pipeline.tools.hash_tree --in ./output --algo md5 --out hashes.json
    python -m ultimate_pipeline.tools.hash_tree --in ./output --ignore "*.log,*.tmp" --out hashes.json
""",
    )
    # Note: Using --in because that's what the docs reference
    ap.add_argument(
        "--in",
        dest="input_dir",
        required=True,
        help="Input directory to hash",
    )
    ap.add_argument(
        "--out",
        dest="output_file",
        required=True,
        help="Output JSON file path",
    )
    ap.add_argument(
        "--algo",
        default="sha256",
        help="Hash algorithm (default: sha256)",
    )
    ap.add_argument(
        "--ignore",
        help="Comma-separated list of additional ignore patterns",
    )
    ap.add_argument(
        "--no-default-ignore",
        action="store_true",
        help="Don't use default ignore patterns",
    )
    ap.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print progress information",
    )

    args = ap.parse_args(argv)

    # Build ignore list
    if args.no_default_ignore:
        ignore_patterns: List[str] = []
    else:
        ignore_patterns = list(DEFAULT_IGNORE_PATTERNS)

    if args.ignore:
        extra = [p.strip() for p in args.ignore.split(",") if p.strip()]
        ignore_patterns.extend(extra)

    if args.verbose:
        print(f"Hashing directory: {args.input_dir}")
        print(f"Algorithm: {args.algo}")
        print(f"Ignore patterns: {len(ignore_patterns)}")

    try:
        result = hash_tree(args.input_dir, algo=args.algo, ignore=ignore_patterns)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"Found {result['_meta']['file_count']} files")
        print(f"Ignored {result['_meta']['ignored_count']} files")

    # Write output
    out_path = Path(args.output_file).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    if args.verbose:
        print(f"Wrote hashes to: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
