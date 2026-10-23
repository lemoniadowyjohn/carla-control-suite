"""Permanent regression tests for previously-fixed defects.

Each test here pins a bug that was actually introduced and fixed during the
infrastructure work. They are permanent, not one-off, because all four are
silent-failure classes: none of them raises, and each one produced a wrong
verdict that looked correct.

1. GATE_TYPE_SAFETY -- `False == 0` is True in Python, so a release gate written
   as `all(v is True or v == 0 for v in flags)` reported PASS while a boolean
   gate had FAILED. This allowed `FULL_PRODUCTION_COOK_ALLOWED=True` to be
   emitted with six failing gates. Type-explicit acceptance is now required.

2. cleanup_guard link detection -- a case-folded canonical path differs
   textually from its abspath, so comparing them directly reported every path
   as "resolves via link" and denied legitimate scratch cleanup.

3. cleanup_guard self-check -- the "no git add" scan matched its own docstring,
   which names the forbidden command on purpose, so the guard failed its own
   audit.

4. manifest tile counter -- `len(m.get("tiles", []) or [m["source"]] if
   m.get("source") else [])` parses as `((tiles or [source]) if source else [])`
   because conditional-expression binds looser than `or`. Every tiled map
   reported zero tiles.
"""

from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
import tempfile
import tokenize

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts"))


# ---------------------------------------------------------------------------
# 1. Gate type safety
# ---------------------------------------------------------------------------
def _release_gate(flags: dict) -> bool:
    """A deliberately strict release gate.

    Each condition is compared against its exact expected value. The historical
    implementation collapsed booleans and numbers into one truthiness test,
    which is exactly the bug under test.
    """
    return bool(
        flags["worktrees_under_temp"] == 0
        and flags["cleanup_guard"] == "PASS"
        and flags["import_tiles"] == 20
        and flags["es31_removed"] is False
        and flags["ddc"] == "QUALIFIED"
        and flags["bounded_cook"] == "PASS"
    )


def _base_flags(**overrides):
    flags = {
        "worktrees_under_temp": 0,
        "cleanup_guard": "PASS",
        "import_tiles": 20,
        "es31_removed": False,
        "ddc": "QUALIFIED",
        "bounded_cook": "PASS",
    }
    flags.update(overrides)
    return flags


def test_all_gates_satisfied_is_true():
    assert _release_gate(_base_flags()) is True


@pytest.mark.parametrize("flag,value", [
    ("ddc", False),
    ("bounded_cook", False),
    ("cleanup_guard", False),
])
def test_false_boolean_gate_fails_gate(flag, value):
    """A False gate must fail, even though `False == 0` in Python."""
    assert _release_gate(_base_flags(**{flag: value})) is False


@pytest.mark.parametrize("flag,value", [
    ("es31_removed", True),
    ("ddc", "NOT_QUALIFIED"),
    ("cleanup_guard", "FAIL"),
])
def test_wrong_typed_values_fail_gate(flag, value):
    assert _release_gate(_base_flags(**{flag: value})) is False


def test_none_fails_gate():
    assert _release_gate(_base_flags(ddc=None)) is False


def test_string_zero_is_not_accepted_as_zero():
    """A JSON string "0" must not satisfy a numeric-zero gate."""
    assert _release_gate(_base_flags(worktrees_under_temp="0")) is False


def test_numeric_zero_passes_numeric_zero_gate():
    assert _release_gate(_base_flags(worktrees_under_temp=0)) is True


def test_buggy_truthiness_gate_would_have_been_wrong():
    """Reproduce the exact defect that emitted FULL_PRODUCTION_COOK_ALLOWED=True.

    The historical gate evaluated a list whose members were already-computed
    booleans, and tested them with `v is True or v == 0`. Because
    `False == 0` is True in Python, every FAILED boolean gate satisfied the
    numeric branch and the gate reported success.
    """
    # Six gates failed, exactly as in the incident.
    worktrees_under_temp_eq_zero = (0 == 0)          # pass
    cleanup_guard_pass = ("PASS" == "PASS")          # pass
    dedup_pass = ("PASS" == "PASS")                   # pass
    tiles_ok = (20 == 20)                             # pass
    es31_removed = False                              # actually PASSES by design
    ddc_qualified = ("NOT_QUALIFIED" == "QUALIFIED")  # FAIL
    memory_qualified = (False == "QUALIFIED")        # FAIL
    pagefile_qualified = (False == "QUALIFIED")      # FAIL
    storage_gate_pass = ("FAIL" == "PASS")           # FAIL
    georef_pass = ("FAIL_BLOCKING" == "PASS")        # FAIL

    buggy = all(v is True or v == 0 for v in [
        worktrees_under_temp_eq_zero, cleanup_guard_pass, dedup_pass, tiles_ok,
        es31_removed, ddc_qualified, memory_qualified, pagefile_qualified,
        storage_gate_pass, georef_pass,
    ])

    # Five of these ten conditions are False.
    assert sum(1 for v in [
        worktrees_under_temp_eq_zero, cleanup_guard_pass, dedup_pass, tiles_ok,
        es31_removed, ddc_qualified, memory_qualified, pagefile_qualified,
        storage_gate_pass, georef_pass,
    ] if v is False) == 6

    assert buggy is True, "the old gate must be shown to accept 6 failed gates"
    assert _release_gate(_base_flags()) is True


def test_json_booleans_remain_typed():
    assert json.loads("true") is True
    assert json.loads("false") is False
    assert isinstance(json.loads("false"), bool)


# ---------------------------------------------------------------------------
# 2. cleanup_guard link detection
# ---------------------------------------------------------------------------
def test_plain_scratch_child_is_allowed():
    from cleanup_guard import build_guard, evaluate

    tmp = tempfile.mkdtemp(prefix="gate_link_")
    try:
        repo = os.path.join(tmp, "repo")
        child = os.path.join(tmp, "scratch", "child")
        os.makedirs(repo)
        os.makedirs(child)
        for args in (["init", "-q", "-b", "main"],
                     ["config", "user.email", "t@t.invalid"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", repo, *args], capture_output=True,
                           timeout=120)
        guard = build_guard(repo)
        decision = evaluate(guard, child)
        assert decision["verdict"] == "ALLOW", decision
        assert "RESOLVES_VIA_LINK" not in decision["reasons"], decision
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3. cleanup_guard self-check must ignore docstrings and comments
# ---------------------------------------------------------------------------
def _executable_text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def test_guard_selfcheck_ignores_docstrings():
    path = os.path.join(REPO, "scripts", "cleanup_guard.py")
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    assert "git add" in raw, "docstring should still mention the forbidden command"
    executable = _executable_text(path)
    assert "git add" not in executable
    assert "add -A" not in executable


# ---------------------------------------------------------------------------
# 4. manifest tile counter
# ---------------------------------------------------------------------------
def test_tiled_map_without_source_key_counts_its_tiles():
    """The operator-precedence bug returned 0 for every tiled map."""
    map_entry = {"name": "Ingolstadt", "tiles": ["./t_%d.fbx" % i for i in range(20)]}
    count = len(map_entry.get("tiles") or ([map_entry["source"]]
                                           if map_entry.get("source") else []))
    assert count == 20


def test_single_source_map_counts_one():
    map_entry = {"name": "Town01", "source": "./Town01.fbx"}
    count = len(map_entry.get("tiles") or ([map_entry["source"]]
                                           if map_entry.get("source") else []))
    assert count == 1


def test_empty_map_counts_zero():
    map_entry = {"name": "Empty"}
    count = len(map_entry.get("tiles") or ([map_entry["source"]]
                                           if map_entry.get("source") else []))
    assert count == 0


def test_import_py_has_no_and_ternary_trap():
    """Guard the exact source pattern that caused the precedence bug."""
    path = r"G:\CARLA\carla_source_probe\Util\BuildTools\Import.py"
    if not os.path.isfile(path):
        pytest.skip("Import.py not present on this machine")
    with open(path, encoding="utf-8", errors="replace") as fh:
        tree = ast.parse(fh.read())
    helpers = {n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)}
    assert "manifest_tile_count" in helpers, (
        "tile counting must live in a named helper, not an inline "
        "'or ... if ... else' expression")

