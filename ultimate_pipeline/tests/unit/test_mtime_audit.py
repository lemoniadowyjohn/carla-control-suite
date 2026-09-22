"""Regression tests to detect newly introduced mtime-based artifact authority.

These tests scan protected production modules for patterns where mtime
(``stat().st_mtime``, ``getmtime``) is used as the **sole or primary**
selection authority — i.e. sorting candidates by mtime and picking [0]
without any prior structural/provenance verification.

Run with: pytest ultimate_pipeline/tests/unit/test_mtime_audit.py -v
"""
from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path, PurePosixPath
from typing import List

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Modules where mtime-as-primary-authority is PROTECTED (must not appear).
# If a new file in these paths introduces a bare "sort by mtime, pick [0]"
# pattern without a structural guard, this test should fail.
PROTECTED_PACKAGES: List[str] = [
    "ultimate_pipeline/tools/artifact_locator.py",
    "ultimate_pipeline/tools/ost_run_protocol_adapter.py",
    "ultimate_pipeline/tools/compare_runs_determinism.py",
    "ultimate_pipeline/tools/carla_smoke_suite.py",
    "ultimate_pipeline/tools/stage_gate_regression.py",
    "ultimate_pipeline/run_determinism_audit.py",
    "ultimate_pipeline/run_full_domain_gap.py",
    "ultimate_pipeline/config/settings.py",
    "ultimate_pipeline/database/run_archiver.py",
    "ultimate_pipeline/domain_gap/run_alignment_and_matching.py",
    "ultimate_pipeline/domain_gap/run_gap_ablation_experiment.py",
    "ultimate_pipeline/domain_gap/run_domain_gap_sweep.py",
    "ultimate_pipeline/experiments/thesis/run_thesis_experiments.py",
    "ultimate_pipeline/experiments/thesis/run_all_experiments.py",
]

# Regex: sort(... key=lambda ... st_mtime / getmtime ...) followed by [0]
# This catches the pattern: sort by mtime then pick the first element.
_MTIME_SORT_PATTERN = re.compile(
    r"\.sort\(\s*key\s*=\s*lambda\s+\w+\s*:\s*"
    r"(?:\w+\.stat\(\)\.st_mtime|os\.path\.getmtime\([^)]*\))"
    r"[^)]*\)",
    re.IGNORECASE,
)

# Also match: max(..., key=lambda ... st_mtime / getmtime)
_MTIME_MAX_PATTERN = re.compile(
    r"max\([^,]+,\s*key\s*=\s*lambda\s+\w+\s*:\s*"
    r"(?:\w+\.stat\(\)\.st_mtime|os\.path\.getmtime\([^)]*\))",
    re.IGNORECASE,
)

# Patterns that indicate a structural guard precedes the mtime selection.
# If a function contains ANY of these before the mtime sort, it's guarded.
_STRUCTURAL_GUARDS = [
    "repaired_sibling",
    "laneSectionFixed",
    "_repaired",
    "structural",
    "provenance",
    "sha256",
    "receipt",
]


def _resolve_protected_path(relpath: str) -> Path:
    """Resolve a forward-slash relative path to an absolute Path on this OS."""
    return REPO_ROOT / PurePosixPath(relpath)


def _relative_to_root(filepath: Path) -> str:
    """Return a forward-slash relative path from REPO_ROOT."""
    return filepath.relative_to(REPO_ROOT).as_posix()


def _has_structural_guard(source: str, mtime_line_idx: int) -> bool:
    """Check if any structural guard pattern appears before the mtime line."""
    lines = source.splitlines()
    preceding = "\n".join(lines[: mtime_line_idx])
    return any(guard.lower() in preceding.lower() for guard in _STRUCTURAL_GUARDS)


def _find_unprotected_mtime_authority(filepath: Path) -> List[dict]:
    """Scan a file for unprotected mtime-as-authority patterns.

    Returns a list of findings with line number and context.
    """
    source = filepath.read_text(encoding="utf-8", errors="replace")
    findings: List[dict] = []

    for pattern in [_MTIME_SORT_PATTERN, _MTIME_MAX_PATTERN]:
        for match in pattern.finditer(source):
            line_idx = source[: match.start()].count("\n")
            line_num = line_idx + 1
            # Check surrounding context for structural guard
            if _has_structural_guard(source, line_idx):
                continue
            # Extract the surrounding function name (best-effort AST)
            func_name = _guess_function_name(source, line_num)
            findings.append(
                {
                    "file": _relative_to_root(filepath),
                    "line": line_num,
                    "function": func_name,
                    "pattern": match.group().strip()[:120],
                }
            )

    return findings


def _guess_function_name(source: str, target_line: int) -> str:
    """Best-effort: find the function containing target_line."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "<unknown>"
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if hasattr(node, "end_lineno") and node.end_lineno:
                if node.lineno <= target_line <= node.end_lineno:
                    return node.name
    return "<module-level>"


class TestMtimeAuthorityRegression:
    """Ensure no unprotected mtime-as-authority is introduced in protected modules."""

    @pytest.mark.parametrize(
        "relpath",
        PROTECTED_PACKAGES,
        ids=lambda p: p.split("/")[-1],
    )
    def test_no_unprotected_mtime_authority(self, relpath: str):
        filepath = _resolve_protected_path(relpath)
        if not filepath.exists():
            pytest.skip(f"{relpath} does not exist")
        findings = _find_unprotected_mtime_authority(filepath)
        if findings:
            details = "\n".join(
                f"  {f['file']}:{f['line']} in {f['function']}: {f['pattern']}"
                for f in findings
            )
            pytest.fail(
                f"Found {len(findings)} unprotected mtime-as-authority pattern(s) "
                f"in {relpath}:\n{details}\n\n"
                "If this is intentional, add a structural guard (e.g., "
                "_repaired_sibling_exists, SHA256 check, provenance receipt) "
                "before the mtime sort/max, or move the pattern to a "
                "non-protected module."
            )

    def test_protected_modules_list_is_nonempty(self):
        """Sanity check: ensure we're actually scanning something."""
        assert len(PROTECTED_PACKAGES) > 0

    def test_all_protected_files_exist(self):
        """Verify all listed protected files exist on disk."""
        missing = []
        for relpath in PROTECTED_PACKAGES:
            if not _resolve_protected_path(relpath).exists():
                missing.append(relpath)
        assert not missing, f"Protected files not found: {missing}"

    def test_pattern_regex_matches_known_patterns(self):
        """Verify the regex catches known mtime patterns."""
        samples = [
            "candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)",
            "osm_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)",
            "xodrs.sort(key=lambda p: p.stat().st_mtime, reverse=True)",
            "run_dirs.sort(key=lambda p: os.path.getmtime(p), reverse=True)",
            "candidates.sort(key=lambda x: os.path.getmtime(x[0]), reverse=True)",
            "return max(log_candidates, key=lambda p: p.stat().st_mtime)",
        ]
        for sample in samples:
            assert (
                _MTIME_SORT_PATTERN.search(sample) or _MTIME_MAX_PATTERN.search(sample)
            ), f"Regex failed to match: {sample}"

    def test_guarded_pattern_not_flagged(self):
        """A pattern with a structural guard should NOT be flagged."""
        guarded_source = textwrap.dedent(
            """\
            def _repaired_sibling_exists(path):
                return True

            def _newest_final_xodr(run_dir):
                semantic = list(run_dir.glob("08_final*_semantic.xodr"))
                repaired = [p for p in semantic if _repaired_sibling_exists(p)]
                pool = repaired or semantic
                pool.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                return pool[0]
        """
        )
        findings = []
        for pattern in [_MTIME_SORT_PATTERN, _MTIME_MAX_PATTERN]:
            for match in pattern.finditer(guarded_source):
                line_idx = guarded_source[: match.start()].count("\n")
                if not _has_structural_guard(guarded_source, line_idx):
                    findings.append(match.group())
        assert findings == [], f"Guarded pattern was incorrectly flagged: {findings}"
