#!/usr/bin/env python3
"""ultimate_pipeline.tools.find_duplicate_files

Quick duplicate-file detector to reduce repo mess.

It hashes files (sha256) under a root directory and reports groups with more than
one identical file. By default it ignores common output directories that are
expected to contain repeated artifacts (e.g., thesis_results/).

Usage
-----
python -m ultimate_pipeline.tools.find_duplicate_files --root .
"""

from __future__ import annotations

import argparse
import hashlib
import os
from collections import defaultdict
from pathlib import Path


DEFAULT_IGNORE_DIRS = {
    '.git', '__pycache__', '.pytest_cache',
    'thesis_results', 'preflight_batch_reports', 'preflight_batch_reports2',
    '_carla_diag_20260115_001749', '_carla_diag_20260115_002053',
}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def find_duplicates(root: Path, ignore_dirs: set[str] | None = None) -> dict[str, list[str]]:
    ignore_dirs = ignore_dirs or set(DEFAULT_IGNORE_DIRS)
    groups: defaultdict[str, list[str]] = defaultdict(list)

    for dirpath, dirnames, filenames in os.walk(root):
        # prune ignored directories
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
        for fn in filenames:
            p = Path(dirpath) / fn
            if not p.is_file() or p.is_symlink():
                continue
            try:
                digest = sha256_file(p)
            except Exception:
                continue
            groups[digest].append(str(p))

    return {k: v for k, v in groups.items() if len(v) > 1}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.', help='root folder to scan')
    ap.add_argument('--out', default='', help='optional json output path')
    args = ap.parse_args()

    dups = find_duplicates(Path(args.root))
    print(f'duplicate groups: {len(dups)}')
    for _, paths in list(dups.items())[:50]:
        print('---')
        for p in paths:
            print(p)

    if args.out:
        Path(args.out).write_text(__import__('json').dumps(dups, indent=2), encoding='utf-8')
        print('wrote:', args.out)


if __name__ == '__main__':
    main()
