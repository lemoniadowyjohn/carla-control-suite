#!/usr/bin/env python3
"""Verify SHA256SUMS.txt without changing project files."""
from pathlib import Path
import hashlib
ROOT=Path(__file__).resolve().parents[1]
def main():
    bad=[]; seen=set()
    lines=(ROOT/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines()
    for line in lines:
        parts=line.split('  ',1)
        if len(parts)!=2: bad.append(f'bad manifest line {line[:50]}');continue
        digest,rel=parts
        p=(ROOT/rel).resolve()
        if not p.is_relative_to(ROOT.resolve()) or rel in seen or not p.is_file(): bad.append(f'invalid path {rel}');continue
        seen.add(rel)
        if hashlib.sha256(p.read_bytes()).hexdigest()!=digest: bad.append(f'bad hash {rel}')
    expected={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and p.name!='SHA256SUMS.txt'}
    if expected!=seen: bad.append(f'manifest completeness mismatch missing={sorted(expected-seen)} unexpected={sorted(seen-expected)}')
    if bad:
        print('FAILED\n'+'\n'.join(bad));return 1
    print(f'PASS: {len(seen)} files sha256 verified (pack bytes only, not scientific evidence)');return 0
if __name__=='__main__': raise SystemExit(main())
