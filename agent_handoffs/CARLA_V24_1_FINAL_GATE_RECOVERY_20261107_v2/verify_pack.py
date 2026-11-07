#!/usr/bin/env python3
"""SHA256 file integrity only. Never treats structural validation as test execution."""
from pathlib import Path
import hashlib, sys
ROOT=Path(__file__).resolve().parent

def verify():
    manifest=ROOT/'SHA256SUMS.txt'
    if not manifest.is_file(): return ['missing SHA256SUMS.txt']
    seen=set(); errors=[]
    for n,line in enumerate(manifest.read_text(encoding='utf-8').splitlines(),1):
        parts=line.split('  ',1)
        if len(parts)!=2 or len(parts[0])!=64:
            errors.append(f'line {n}: malformed'); continue
        digest,relative=parts
        if relative in seen: errors.append(f'duplicate {relative}');continue
        seen.add(relative)
        p=(ROOT/relative).resolve()
        if not p.is_relative_to(ROOT.resolve()) or not p.is_file():
            errors.append(f'unsafe/missing {relative}');continue
        if hashlib.sha256(p.read_bytes()).hexdigest()!=digest: errors.append(f'bad SHA256 {relative}')
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and p.name!='SHA256SUMS.txt' and '__pycache__' not in p.parts}
    if actual!=seen: errors.append(f'manifest inventory missing={sorted(actual-seen)}, extra={sorted(seen-actual)}')
    return errors

if __name__=='__main__':
    errors=verify()
    if errors:
        print('FAIL\n'+'\n'.join(errors));sys.exit(1)
    print('PASS: all pack files match SHA256SUMS.txt. NO CARLA tests or science proven.')
