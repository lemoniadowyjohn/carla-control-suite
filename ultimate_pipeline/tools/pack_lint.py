#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit-pack generation lint (V5 packaging closure, section 12).

The V4 pack shipped authoritative files whose *own headers* still declared an
older generation (``00_MASTER_EXECUTION.md`` titled "audited v3" in a V4 pack,
``MODULE_INTEGRATION_MATRIX.md`` titled "v3"), and inherited prompts referenced
companion packs by stale ``v2``/``v3`` names. Nothing rejected these at
generation time, so a reader could not tell which generation a file belonged to.

This module is the **canonical owner** of pack-generation validation. It is a
lint, not a second authority: it reads the pack's own manifest and SHA-256
manifest and reports defects. It never rewrites pack content.

Checks
------
1. ``stale_top_level_version``   -- an authoritative top-level file declares a
   generation other than the pack's own.
2. ``stale_companion_reference`` -- a companion pack/archive name is referenced
   with a generation different from the pack's own.
3. ``task_count_mismatch``       -- ``prompt_manifest.json`` task_count does not
   match the number of task entries.
4. ``missing_referenced_prompt`` -- a manifest task's ``file`` does not exist.
5. ``missing_referenced_module`` -- a referenced module/source path is absent.
6. ``sha256_manifest_coverage``  -- a file in the pack is absent from the
   SHA-256 manifest, or a manifest entry does not exist / mismatches.
7. ``documented_count_mismatch`` -- the README/controller states a prompt count
   that the pack does not actually contain (the "seven bounded implementation
   prompts" class of defect).

Usage:
    python -m ultimate_pipeline.tools.pack_lint <pack_dir> \
        [--expect-version V5] [--expect-task-count 7] [--json]

Exit code 0 when no defects, 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "DEFECT_CODES",
    "AUTHORITATIVE_TOP_LEVEL",
    "lint_pack",
    "main",
]

DEFECT_CODES = (
    "stale_top_level_version",
    "stale_companion_reference",
    "task_count_mismatch",
    "missing_referenced_prompt",
    "missing_referenced_module",
    "sha256_manifest_coverage",
    "documented_count_mismatch",
)

#: Files that state a pack generation in their own body and therefore must agree
#: with the pack's generation.
AUTHORITATIVE_TOP_LEVEL = (
    "00_MASTER_EXECUTION.md",
    "MODULE_INTEGRATION_MATRIX.md",
    "00_V5_INCREMENTAL_MASTER.md",
    "README.md",
    "CARLA_GAP_CLOSURE_PACK_AUDITED_V4_README.md",
    "CARLA_V5_INCREMENTAL_AUDIT_README.md",
)

_SHA_LINE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$")
#: Archive/companion names that embed a generation, e.g. CARLA_..._AUDITED_V4_...zip
_COMPANION_REF = re.compile(
    r"([A-Za-z0-9_.\-]*(?:AUDITED_V\d|GAP_CLOSURE[A-Za-z0-9_.\-]*)[A-Za-z0-9_.\-]*\.(?:zip|txt))",
    re.IGNORECASE,
)
#: A file's *own* self-declared generation, as opposed to historical references
#: to earlier generations inside prose ("this pack extends audited v2").
_SELF_DECLARATION = re.compile(
    r"^\s*#.*?\b(?:audited|v)\s*v?(\d)\b", re.IGNORECASE | re.MULTILINE
)
_SHA256_MANIFEST_NAMES = ("SHA256SUMS.txt", "SHA256SUMS_AUDITED_V4.txt")


def _norm_version(token: str) -> Optional[str]:
    m = re.fullmatch(r"v?(\d)", token.strip().lower())
    return m.group(1) if m else None


def _find_sha_manifest(pack_dir: Path) -> Optional[Path]:
    for name in _SHA256_MANIFEST_NAMES:
        candidate = pack_dir / name
        if candidate.is_file():
            return candidate
    for path in sorted(pack_dir.rglob("SHA256SUMS*.txt")):
        return path
    return None


def _parse_sha_manifest(path: Path) -> Dict[str, str]:
    entries: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        m = _SHA_LINE.match(line.strip())
        if m:
            entries[m.group(2).replace("\\", "/")] = m.group(1).lower()
    return entries


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


#: A bounded implementation prompt is named `<TASKID>_<FINDINGID>_...md`, e.g.
#: ``D16_NEW202_fail_closed_run_pack_finalization.md`` or ``A01_NEW123_...md``.
_TASK_PROMPT_NAME = re.compile(r"^[A-Z]\d{1,2}_[A-Za-z0-9_.\-]+\.md$")


def _is_task_prompt(path: Path) -> bool:
    return bool(_TASK_PROMPT_NAME.match(path.name)) and path.parent.name.lower().startswith("phase_")


def _load_manifest(pack_dir: Path) -> Optional[Dict[str, Any]]:
    for name in ("prompt_manifest.json", "AUDIT_REPORT_V4.json", "AUDIT_REPORT_V5_INCREMENTAL.json"):
        for candidate in [pack_dir / name, *sorted(pack_dir.rglob(name))]:
            if candidate.is_file():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return None
    return None


def _detect_pack_version(pack_dir: Path, manifest: Optional[Dict[str, Any]]) -> Optional[str]:
    """Best-effort detection of the pack's own generation (bare digits, e.g. "5")."""
    if manifest:
        schema = str(manifest.get("schema") or "")
        m = re.search(r"(?:V|PACK_|AUDITED_)(\d)\b", schema, re.IGNORECASE)
        if m:
            return m.group(1)
    name = pack_dir.name
    m = re.search(r"(?:_V|_AUDITED_V)(\d)\b", name, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"_(\d{4}-\d{2}-\d{2})", name)
    return None


def lint_pack(
    pack_dir: str | Path,
    *,
    expect_version: Optional[str] = None,
    expect_task_count: Optional[int] = None,
    extra_companion_versions: Iterable[str] = (),
) -> Dict[str, Any]:
    """Lint an audit pack. Returns a machine-readable report."""
    root = Path(pack_dir).expanduser().resolve()
    defects: List[Dict[str, Any]] = []

    def defect(code: str, detail: str, **extra: Any) -> None:
        defects.append({"code": code, "detail": detail, **extra})

    if not root.is_dir():
        return {
            "schema": "PACK_LINT/v1",
            "pack_dir": root.as_posix(),
            "pack_version": None,
            "status": "FAIL",
            "defects": [{"code": "pack_missing", "detail": f"not a directory: {root.as_posix()}"}],
        }

    manifest = _load_manifest(root)
    pack_version = _detect_pack_version(root, manifest)
    if expect_version is not None:
        pack_version = expect_version

    allowed_companion = {pack_version} if pack_version else set()
    allowed_companion |= {_norm_version(v) for v in extra_companion_versions if _norm_version(v)}

    # 1. stale top-level generation labels -----------------------------------
    # A file is stale when its *own* title/self-declared generation names an
    # EARLIER pack than the pack it ships in. Prose that legitimately refers to
    # an earlier generation ("this pack extends audited v2") is not a defect.
    checked_top_level: List[str] = []
    for name in AUTHORITATIVE_TOP_LEVEL:
        for path in [root / name, *sorted(root.rglob(name))]:
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            checked_top_level.append(rel)
            text = path.read_text(encoding="utf-8", errors="replace")
            m = _SELF_DECLARATION.search(text)
            if m and pack_version is not None and m.group(1) != pack_version:
                defect(
                    "stale_top_level_version",
                    f"{rel}: self-declares generation v{m.group(1)} but ships in a v{pack_version} pack",
                    file=rel,
                    found=m.group(1),
                    expected=pack_version,
                )
            break  # only the canonical copy of a given top-level name

    # 1b. a top-level file that declares NO generation at all -----------------
    for name in AUTHORITATIVE_TOP_LEVEL:
        for path in [root / name, *sorted(root.rglob(name))]:
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            if not _SELF_DECLARATION.search(text):
                defect(
                    "stale_top_level_version",
                    f"{rel}: authoritative top-level file declares no pack generation",
                    file=rel,
                    found=None,
                    expected=pack_version,
                )
            break

    # 2. stale companion-pack references -------------------------------------
    for path in sorted(root.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        for m in _COMPANION_REF.finditer(text):
            ref = m.group(1)
            # `(?!\d)` rather than `\b`: in `AUDITED_V2_2026-01-01.zip` the digit
            # is followed by `_`, which is a word character, so \b never matches.
            vm = re.search(r"(?:AUDITED_)?V(\d)(?!\d)", ref, re.IGNORECASE)
            if not vm or not allowed_companion:
                continue
            found = vm.group(1)
            if found in allowed_companion:
                continue
            defect(
                "stale_companion_reference",
                f"{rel}: references companion pack {ref!r} with a generation other than v{pack_version}",
                file=rel,
                found=found,
                expected=pack_version,
            )

    # 3-5. manifest task accounting ------------------------------------------
    task_entries: List[Dict[str, Any]] = []
    if manifest and isinstance(manifest.get("tasks"), list):
        task_entries = [t for t in manifest["tasks"] if isinstance(t, dict)]
        declared = manifest.get("task_count")
        if isinstance(declared, int) and declared != len(task_entries):
            defect(
                "task_count_mismatch",
                f"prompt_manifest task_count={declared} but {len(task_entries)} task entries exist",
                declared=declared,
                actual=len(task_entries),
            )
        for task in task_entries:
            rel = task.get("file")
            if not rel:
                continue
            if not (root / rel).is_file() and not list(root.rglob(Path(rel).name)):
                defect(
                    "missing_referenced_prompt",
                    f"manifest task references a prompt that does not exist: {rel}",
                    file=rel,
                )
        counted = len(task_entries)
    else:
        # No task manifest: count the actual bounded implementation prompts so a
        # controller/README claim about "N prompts" can still be verified.
        counted = len(sorted(p for p in root.rglob("*.md") if _is_task_prompt(p)))

    if expect_task_count is not None and counted != expect_task_count:
        defect(
            "documented_count_mismatch",
            f"pack documents {expect_task_count} task prompts but {counted} are present",
            expected=expect_task_count,
            actual=counted,
        )

    # 5. referenced modules must exist ---------------------------------------
    for name in ("MODULE_LIST.txt",):
        for path in [root / name, *sorted(root.rglob(name))]:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                entry = line.strip()
                if not entry or entry.startswith("#"):
                    continue
                if not re.search(r"\.py$", entry):
                    continue
                if not (root / entry).is_file() and not list(root.rglob(Path(entry).name)):
                    defect(
                        "missing_referenced_module",
                        f"{path.relative_to(root).as_posix()} references a module that does not exist: {entry}",
                        file=entry,
                    )
            break

    # 6. SHA-256 manifest coverage -------------------------------------------
    sha_manifest = _find_sha_manifest(root)
    sha_report: Dict[str, Any] = {"manifest": None, "covered": 0, "problems": []}
    if sha_manifest is None:
        sha_report["problems"].append("no SHA256SUMS manifest found in the pack")
        defect("sha256_manifest_coverage", "no SHA256SUMS manifest found in the pack")
    else:
        entries = _parse_sha_manifest(sha_manifest)
        sha_report["manifest"] = sha_manifest.relative_to(root).as_posix()
        sha_report["covered"] = len(entries)
        base = sha_manifest.parent
        for rel, expected in sorted(entries.items()):
            target = base / rel
            if not target.is_file():
                defect("sha256_manifest_coverage",
                       f"SHA256SUMS lists a file that does not exist: {rel}", file=rel)
                sha_report["problems"].append(f"missing: {rel}")
                continue
            actual = _sha256_file(target)
            if actual != expected:
                defect("sha256_manifest_coverage",
                       f"SHA256SUMS digest mismatch for {rel}", file=rel,
                       expected=expected, actual=actual)
                sha_report["problems"].append(f"mismatch: {rel}")
        # Coverage: every non-generated pack file should be listed.
        listed = {rel for rel in entries}
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            if rel in listed or path.name.startswith(".") or "__pycache__" in rel:
                continue
            if path.suffix.lower() in {".pyc"}:
                continue
            if not (path.parent == base and path.name == sha_manifest.name):
                # Only require coverage for files that live beside the manifest;
                # nested companion archives legitimately carry their own manifests.
                if path.parent != base:
                    continue
                defect("sha256_manifest_coverage",
                       f"pack file is not covered by SHA256SUMS: {rel}", file=rel)
                sha_report["problems"].append(f"uncovered: {rel}")

    by_code: Dict[str, int] = {}
    for d in defects:
        by_code[d["code"]] = by_code.get(d["code"], 0) + 1

    return {
        "schema": "PACK_LINT/v1",
        "pack_dir": root.as_posix(),
        "pack_version": pack_version,
        "status": "PASS" if not defects else "FAIL",
        "defect_count": len(defects),
        "defects_by_code": by_code,
        "defects": defects,
        "top_level_files_checked": checked_top_level,
        "task_count": counted,
        "sha256_manifest": sha_report,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("pack_dir", help="path to the extracted audit pack directory")
    parser.add_argument("--expect-version", help="expected pack generation, e.g. V5")
    parser.add_argument("--expect-task-count", type=int, help="expected number of task prompts")
    parser.add_argument("--json", action="store_true", help="emit the full report as JSON")
    args = parser.parse_args(argv)

    report = lint_pack(
        args.pack_dir,
        expect_version=args.expect_version,
        expect_task_count=args.expect_task_count,
    )
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            f"[pack_lint] {report['pack_dir']} version=v{report['pack_version']} "
            f"status={report['status']} defects={report['defect_count']}\n"
        )
        for d in report["defects"]:
            sys.stdout.write(f"  - {d['code']}: {d['detail']}\n")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
