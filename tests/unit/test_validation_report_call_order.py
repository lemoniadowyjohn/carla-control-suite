"""Guard: ``ValidationReport.add()`` calls must be level-first, package-wide.

``ValidationReport.add(level, stage, message)`` takes the level *first*.  A call
that passes the semantic stage key first (``vreport.add("enrichment", "error", ...)``)
silently lands in the ``warnings`` bucket instead of ``errors``: no exception,
no failing gate -- just a mis-classified report.  Commit ``56efb2cb`` fixed the
26 reversed call sites that existed in ``ultimate_pipeline/pipeline_stages/``.
A follow-up fix made every remaining ``ultimate_pipeline/`` call site
level-first (``main_pipeline.py`` and ``ultimate_pipeline/quality/``).  This
test keeps the whole package's fix from regressing.

Scope
-----
All of ``ultimate_pipeline/`` is walked (nested ``tests`` directories and
``__pycache__`` are skipped).  Every ``.add(...)`` call whose receiver name
ends in ``vreport`` (``self.vreport.add``, ``vreport.add``) is checked: the
first positional argument must be a string literal that is one of
``{"error", "warning", "success", "skipped"}``.

Mandated-Limitations
--------------------
1. ``ALLOWLIST`` is empty because a package-wide AST measurement found **0**
   non-constant first positional arguments among the 59
   ``vreport.add(...)`` calls in scope -- there is nothing legitimate to
   exempt.  If a future call genuinely needs a dynamic level, that is a design
   decision: fix the call (or extend the checker deliberately), do not widen
   the allowlist to make a red test green.
2. The 26 reversed sites fixed by ``56efb2cb`` were all inside
   ``pipeline_stages/`` (stage_04, stage_05, stage_07, stage_08_integrity,
   stage_09, stage_12); the 20 additional sites fixed in this change span
   ``main_pipeline.py`` and ``ultimate_pipeline/quality/``.

Paths are resolved from this test file's location so the guard behaves the same
when pytest is started from the worktree root or from anywhere else.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, List, NamedTuple, Optional, Set

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOT = REPO_ROOT / "ultimate_pipeline"

VALID_LEVELS = frozenset({"error", "warning", "success", "skipped"})

# Empty on purpose -- see Mandated-Limitations item (1): 0 non-constant first
# positional arguments exist in scope package-wide.
ALLOWLIST: dict[str, Set[int]] = {}

# Measured package-wide (all of ultimate_pipeline/, nested tests/ excluded):
# 59 calls in scope.  The guard asserts a floor (>= 59) instead of the exact
# number so that *adding* level-first calls never turns it red, while a walk
# that silently matches nothing still fails.
MIN_EXPECTED_CALLS = 59
MEASURED_CALL_COUNT = 59


class AddCall(NamedTuple):
    path: str
    lineno: int
    first_arg: Optional[ast.expr]


def _receiver_ends_in_vreport(node: ast.AST) -> bool:
    """True for receivers spelled ``self.vreport`` / ``vreport`` (any prefix)."""
    if isinstance(node, ast.Name):
        return node.id.endswith("vreport")
    if isinstance(node, ast.Attribute):
        return node.attr.endswith("vreport")
    return False


def _is_vreport_add(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add"
        and _receiver_ends_in_vreport(node.func.value)
    )


def _iter_scope_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root).parts
        if "__pycache__" in parts:
            continue
        if "tests" in parts[:-1]:
            continue
        yield path


def _relative(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:  # pragma: no cover - defensive, outside repo root
        return path.as_posix()


def collect_add_calls(source: str, label: str) -> List[AddCall]:
    """Return every ``<receiver>vreport.add(...)`` call in *source*."""
    tree = ast.parse(source, filename=label)
    calls: List[AddCall] = []
    for node in ast.walk(tree):
        if _is_vreport_add(node):
            first = node.args[0] if node.args else None
            calls.append(AddCall(label, node.lineno, first))
    return calls


def describe_first_arg(node: Optional[ast.expr]) -> str:
    if node is None:
        return "no positional argument"
    if isinstance(node, ast.Constant):
        return f"constant {node.value!r}"
    return f"{type(node).__name__} expression"


def scan_package_dir(root: Path) -> tuple[List[AddCall], List[str]]:
    calls: List[AddCall] = []
    for path in _iter_scope_files(root):
        # utf-8-sig: some tracked sources carry a UTF-8 BOM.
        calls.extend(
            collect_add_calls(path.read_text(encoding="utf-8-sig"), _relative(path))
        )

    violations: List[str] = []
    for call in calls:
        allowed = ALLOWLIST.get(call.path, set())
        if call.lineno in allowed:
            continue
        keeps_level = (
            isinstance(call.first_arg, ast.Constant)
            and isinstance(call.first_arg.value, str)
            and call.first_arg.value in VALID_LEVELS
        )
        if not keeps_level:
            violations.append(
                f"{call.path}:{call.lineno}: first positional argument is "
                f"{describe_first_arg(call.first_arg)}, expected one of "
                f"{sorted(VALID_LEVELS)}"
            )
    return calls, violations


def test_scan_root_exists() -> None:
    assert SCAN_ROOT.is_dir(), f"ultimate_pipeline directory not found: {SCAN_ROOT}"


def test_validation_report_add_is_level_first_package_wide() -> None:
    calls, violations = scan_package_dir(SCAN_ROOT)

    assert len(calls) >= MIN_EXPECTED_CALLS, (
        f"AST walk found only {len(calls)} vreport.add() call(s) under "
        f"{SCAN_ROOT} (expected at least {MIN_EXPECTED_CALLS}; measured "
        f"{MEASURED_CALL_COUNT}). The check is probably "
        f"looking at the wrong directory."
    )

    assert not violations, (
        f"{len(violations)} ValidationReport.add() call(s) are not level-first "
        f"(level must be the first positional argument, one of "
        f"{sorted(VALID_LEVELS)}):\n  " + "\n  ".join(violations)
    )


def test_detector_flags_reversed_level_and_accepts_level_first() -> None:
    """Self-check of the AST logic on synthetic sources (no repo dependence)."""
    source = "\n".join(
        [
            "self.vreport.add('error', 'stage', 'msg')",       # ok
            "vreport.add('warning', 'stage', 'msg')",          # ok
            "self.vreport.add('stage', 'error', 'msg')",       # reversed
            "self.vreport.add(level, 'stage', 'msg')",         # non-constant
            "self.vreport.add()",                              # no positionals
            "other_report.add('stage', 'error', 'msg')",       # not in scope
            "self.vreport.add_warning('stage', 'msg')",        # different method
        ]
    )
    calls = collect_add_calls(source, "synthetic.py")
    assert [call.lineno for call in calls] == [1, 2, 3, 4, 5]
    assert [call.first_arg is not None for call in calls] == [True] * 4 + [False]
    assert all(
        isinstance(call.first_arg, ast.Constant) and call.first_arg.value in VALID_LEVELS
        for call in calls[:2]
    )

    violations = []
    for call in calls:
        if not (
            isinstance(call.first_arg, ast.Constant)
            and isinstance(call.first_arg.value, str)
            and call.first_arg.value in VALID_LEVELS
        ):
            violations.append(f"{call.path}:{call.lineno}")
    assert violations == ["synthetic.py:3", "synthetic.py:4", "synthetic.py:5"]
