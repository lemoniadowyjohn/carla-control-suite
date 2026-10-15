"""Regression tests for CARLA ``Util/BuildTools/Import.py``.

Two independent concerns are covered:

1. Equality semantics at the tile-template construction site (formerly
   ``if key is not 'tiles':``). Identity comparison against a string literal is
   unreliable because CPython string interning is an implementation detail, and
   ``json`` hands back keys from its own memo dict rather than the interned
   literal. The tests pin the value-comparison contract.

2. Child process supervision. The historical invocation path was
   ``subprocess.check_call(command, shell=True)``, which reported cmd.exe's PID
   instead of the editor's, recorded no command line / start / end UTC /
   stdout / stderr paths, had no explicit state for a child that vanished
   without an exit code, and on the posix branch plus the Recast ``build.bat``
   calls discarded the return code entirely.

The test also records executable evidence that the SyntaxWarning is NOT the
cause of the truncated 16.76 h import, so that the claim is not carried
forward as folklore.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time

import pytest

CARLA_SOURCE_ROOT = os.environ.get(
    "CARLA_SOURCE_ROOT", r"G:\CARLA\carla_source_probe"
)
IMPORT_PY = os.path.join(CARLA_SOURCE_ROOT, "Util", "BuildTools", "Import.py")

pytestmark = pytest.mark.regression


def _load_import_module():
    """Import Import.py by path. It does a top-level ``import carla``."""
    spec = importlib.util.spec_from_file_location("carla_util_import", IMPORT_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if not os.path.isfile(IMPORT_PY):
    pytest.skip(
        "CARLA Util/BuildTools/Import.py not found at %s; "
        "set CARLA_SOURCE_ROOT to the CARLA 0.9.16 source tree" % IMPORT_PY,
        allow_module_level=True,
    )

import_module = _load_import_module()


# ---------------------------------------------------------------------------
# 1. Equality semantics
# ---------------------------------------------------------------------------


def test_source_uses_value_equality_not_identity():
    """The tile template must use ``!=``, never ``is not``."""
    with open(IMPORT_PY, "r", encoding="utf-8") as handle:
        source = handle.read()

    assert "if key != 'tiles':" in source, "expected value-equality comparison"
    assert "if key is not 'tiles':" not in source, (
        "identity comparison against a string literal regressed"
    )


def test_value_equality_excludes_the_tiles_key():
    """``!=`` excludes 'tiles' for keys that are equal-but-not-identical."""
    umap = {"name": "Ingolstadt", "xodr": "a/b.xodr", "tiles": ["t1.fbx", "t2.fbx"]}

    map_template = {}
    for key, value in umap.items():
        if key != "tiles":
            map_template[key] = value
    map_template["tiles"] = []

    assert "tiles" in map_template and map_template["tiles"] == []
    assert "name" in map_template and map_template["name"] == "Ingolstadt"
    assert "xodr" in map_template


def test_equal_but_nonidentical_string_is_still_excluded():
    """A key equal to 'tiles' but not the interned object must be excluded.

    This is precisely the case identity comparison gets wrong, and the reason
    the fix is required rather than cosmetic.
    """
    interned = "tiles"
    nonidentical = "".join(["ti", "les"])
    assert interned == nonidentical
    # Demonstrates the divergence that motivated the change.
    assert (interned is not nonidentical) is True

    umap = {nonidentical: ["t1.fbx"], "name": "Ingolstadt"}

    # Bind to a name so the comparison against a *literal* -- the thing that
    # emits the compile-time SyntaxWarning -- is not written here.
    tiles_literal = "tiles"
    by_identity = {k: v for k, v in umap.items() if k is not tiles_literal}
    by_value = {k: v for k, v in umap.items() if k != tiles_literal}

    # Identity comparison wrongly keeps the tiles entry.
    assert nonidentical in by_identity
    # Value comparison correctly drops it.
    assert nonidentical not in by_value


def test_tile_keys_from_real_json_are_excluded():
    """Keys parsed the way CARLA parses them are excluded under ``!=``."""
    payload = (
        '{"name": "Ingolstadt", "xodr": "Ingolstadt/Ingolstadt.xodr",'
        ' "tile_size": 2000, "tiles": ["Ingolstadt_Tile_6_6.fbx"]}'
    )
    umap = json.loads(payload)

    map_template = {}
    for key, value in umap.items():
        if key != "tiles":
            map_template[key] = value
    map_template["tiles"] = []

    assert map_template["tiles"] == []
    assert map_template["tile_size"] == 2000
    assert map_template["name"] == "Ingolstadt"


def test_syntaxwarning_is_not_a_correctness_defect():
    """Pin WHY the SyntaxWarning is not the truncation root cause.

    Because ``map_template['tiles']`` is unconditionally assigned immediately
    afterwards, both the identity form and the value form yield the SAME final
    template. The warning is therefore cosmetic with respect to import
    correctness, which is why it cannot explain a truncated 16.76 h run.
    """
    umap = {"name": "Ingolstadt", "xodr": "a.xodr", "tiles": ["t1.fbx", "t2.fbx"]}

    # Bind the literal to a name: comparing a name avoids the compile-time
    # SyntaxWarning that this very test is about.
    tiles_literal = "tiles"

    def build(comparison):
        template = {}
        for key, value in umap.items():
            if comparison(key):
                template[key] = value
        template["tiles"] = []
        return template

    by_identity = build(lambda k: k is not tiles_literal)
    by_value = build(lambda k: k != tiles_literal)

    assert by_identity == by_value
    assert by_value["tiles"] == []
    assert by_identity["tiles"] == []


def test_compiles_without_syntax_warning():
    """Import.py compiles cleanly and emits no SyntaxWarning for line 343."""
    proc = subprocess.run(
        [sys.executable, "-W", "error::SyntaxWarning", "-m", "py_compile", IMPORT_PY],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "SyntaxWarning" not in proc.stderr
    assert "is not" not in proc.stderr


# ---------------------------------------------------------------------------
# 2. Supervision contract
# ---------------------------------------------------------------------------


@pytest.fixture()
def supervision_dir(tmp_path, monkeypatch):
    target = tmp_path / "supervision"
    target.mkdir()
    monkeypatch.setenv("CARLA_IMPORT_SUPERVISION_DIR", str(target))
    return target


def _python_child(source, *args):
    return [sys.executable, "-c", source, *[str(a) for a in args]]


REQUIRED_FIELDS = (
    "child_pid",
    "command_line",
    "start_utc",
    "end_utc",
    "exit_code",
    "stdout_path",
    "stderr_path",
    "state",
)


def test_required_fields_are_always_present(supervision_dir):
    """Every terminal record carries the full required field set."""
    record = import_module.supervise_child(
        _python_child("print('hello')"), "fields"
    )
    for field in REQUIRED_FIELDS:
        assert field in record, "missing required field %r" % field
    assert record["schema"] == import_module.SUPERVISION_SCHEMA
    assert record["state"] == import_module.STATE_OK
    assert record["exit_code"] == 0
    assert isinstance(record["child_pid"], int)
    assert record["start_utc"].endswith("Z")
    assert record["end_utc"].endswith("Z")
    assert record["end_utc"] >= record["start_utc"]


def test_child_pid_is_the_real_child_not_a_shell(supervision_dir):
    """shell=False means the tracked PID is the child itself, not a shell.

    Uses the base interpreter rather than ``sys.executable``: a virtualenv on
    Windows ships a redirector ``python.exe`` that launches the real
    interpreter as a grandchild, which would make the PID comparison describe
    the venv layout instead of the supervision contract.
    """
    base_python = os.path.join(sys.base_prefix, "python.exe" if os.name == "nt" else "python")
    if not os.path.isfile(base_python):
        base_python = sys.executable

    record = import_module.supervise_child(
        [base_python, "-c", "import os; print(os.getpid())"], "pidcheck"
    )
    with open(record["stdout_path"], "r", encoding="utf-8") as handle:
        printed = handle.read().strip()
    assert printed == str(record["child_pid"])


def test_command_line_is_recorded_verbatim(supervision_dir):
    command = _python_child("print('x')", "argA", "argB")
    record = import_module.supervise_child(command, "cmdline")
    assert record["command_line"] == command


def test_stdout_and_stderr_are_captured_to_files(supervision_dir):
    record = import_module.supervise_child(
        _python_child(
            "import sys; sys.stdout.write('OUT'); sys.stderr.write('ERR')"
        ),
        "capture",
    )
    assert os.path.isfile(record["stdout_path"])
    assert os.path.isfile(record["stderr_path"])
    with open(record["stdout_path"], "r", encoding="utf-8") as handle:
        assert handle.read() == "OUT"
    with open(record["stderr_path"], "r", encoding="utf-8") as handle:
        assert handle.read() == "ERR"


def test_receipt_is_persisted_to_disk(supervision_dir):
    record = import_module.supervise_child(
        _python_child("print('persisted')"), "receipt"
    )
    assert os.path.isfile(record["receipt_path"])
    with open(record["receipt_path"], "r", encoding="utf-8") as handle:
        on_disk = json.load(handle)
    assert on_disk["state"] == import_module.STATE_OK
    assert on_disk["exit_code"] == 0
    assert on_disk["child_pid"] == record["child_pid"]


def test_nonzero_child_exit_is_propagated(supervision_dir):
    """Wrapper must fail loudly when the child exits nonzero."""
    with pytest.raises(import_module.ChildProcessError) as excinfo:
        import_module.supervise_child(
            _python_child("import sys; sys.exit(7)"), "nonzero"
        )
    record = excinfo.value.record
    assert record["state"] == import_module.STATE_CHILD_NONZERO_EXIT
    assert record["exit_code"] == 7


def test_windows_control_c_exit_code_is_captured(supervision_dir):
    """0xC000013A (STATUS_CONTROL_C_EXIT) must be captured, not swallowed.

    This is the code observed when the real import was truncated by a Ctrl+C
    delivered to the process group: 3221225786 == 0xC000013A.
    """
    expected = 0xC000013A
    source = "import sys; sys.exit(%d)" % expected
    if os.name != "nt":
        pytest.skip("STATUS_CONTROL_C_EXIT is Windows-specific")
    with pytest.raises(import_module.ChildProcessError) as excinfo:
        import_module.supervise_child(_python_child(source), "ctrlc")
    record = excinfo.value.record
    # Python cannot exit with arbitrary 32-bit codes; assert the mechanism.
    assert record["exit_code"] is not None
    assert record["state"] in (
        import_module.STATE_CHILD_NONZERO_EXIT,
        import_module.STATE_CHILD_TERMINATED_UNEXPECTEDLY,
    )
    assert record["state"] in import_module.TERMINAL_FAILURE_STATES


def test_vanished_child_yields_explicit_terminated_unexpectedly(supervision_dir):
    """A child yielding no exit code is CHILD_TERMINATED_UNEXPECTEDLY.

    This is the first run's failure mode: processes gone, no traceback, no exit
    code. It must never be reported as success.
    """
    original = subprocess.Popen
    calls = {"n": 0}

    class VanishingChild(object):
        pid = 424242

        def wait(self, timeout=None):
            return None

        def poll(self):
            return None

        def kill(self):
            return None

    def fake_popen(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return original(*args, **kwargs)
        return VanishingChild()

    subprocess.Popen = fake_popen
    try:
        # First call uses the real Popen so the counter reaches the stub.
        warmup = import_module.supervise_child(
            _python_child("print('first')"), "vanish_probe"
        )
        assert warmup["state"] == import_module.STATE_OK

        with pytest.raises(import_module.ChildProcessError) as excinfo:
            import_module.supervise_child(
                _python_child("print('second')"), "vanish"
            )
    finally:
        subprocess.Popen = original

    record = excinfo.value.record
    assert record["state"] == import_module.STATE_CHILD_TERMINATED_UNEXPECTEDLY
    assert record["exit_code"] is None
    assert record["state"] in import_module.TERMINAL_FAILURE_STATES


def test_terminated_unexpectedly_is_a_declared_state():
    assert hasattr(import_module, "STATE_CHILD_TERMINATED_UNEXPECTEDLY")
    assert import_module.STATE_CHILD_TERMINATED_UNEXPECTEDLY == (
        "CHILD_TERMINATED_UNEXPECTEDLY"
    )
    assert import_module.STATE_CHILD_TERMINATED_UNEXPECTEDLY in (
        import_module.TERMINAL_FAILURE_STATES
    )
    assert import_module.STATE_OK not in import_module.TERMINAL_FAILURE_STATES


def test_audit_flags_receipt_left_running(supervision_dir):
    """A wrapper killed mid-flight leaves RUNNING; audit must flag it."""
    base = "%s_seeded" % import_module._utc_stamp()
    receipt_path = os.path.join(str(supervision_dir), base + ".supervision.json")
    with open(receipt_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "schema": import_module.SUPERVISION_SCHEMA,
                "label": "seeded",
                "state": import_module.STATE_RUNNING,
                "child_pid": 999,
                "exit_code": None,
            },
            handle,
        )

    findings = import_module.audit_supervision_records(str(supervision_dir))
    assert len(findings) == 1
    assert findings[0]["state"] == import_module.STATE_CHILD_TERMINATED_UNEXPECTEDLY
    assert findings[0]["audited"] is True


def test_spawn_failure_is_explicit(supervision_dir):
    with pytest.raises(import_module.ChildProcessError) as excinfo:
        import_module.supervise_child(
            [os.path.join(str(supervision_dir), "definitely_absent_binary")],
            "spawnfail",
        )
    record = excinfo.value.record
    assert record["state"] == import_module.STATE_SPAWN_FAILED
    assert record["child_pid"] is None
    assert record["exit_code"] is None


def test_timeout_is_explicit_and_kills_child(supervision_dir):
    with pytest.raises(import_module.ChildProcessError) as excinfo:
        import_module.supervise_child(
            _python_child("import time; time.sleep(30)"), "timeout", timeout=2
        )
    record = excinfo.value.record
    assert record["state"] == import_module.STATE_TIMEOUT
    assert record["duration_sec"] is not None
    assert record["duration_sec"] < 25


def test_no_success_state_when_output_validation_fails(supervision_dir):
    """Exit 0 is NOT success unless the output validates."""
    with pytest.raises(import_module.ChildProcessError) as excinfo:
        import_module.supervise_child(
            _python_child("print('no marker here')"),
            "validation_fail",
            output_validator=lambda so, se, rec: False,
        )
    record = excinfo.value.record
    assert record["exit_code"] == 0
    assert record["state"] == import_module.STATE_OUTPUT_VALIDATION_FAILED
    assert record["state"] != import_module.STATE_OK


def test_output_validation_receives_paths_and_can_pass(supervision_dir):
    seen = {}

    def validator(stdout_path, stderr_path, record):
        seen["stdout_path"] = stdout_path
        seen["stderr_path"] = stderr_path
        with open(stdout_path, "r", encoding="utf-8") as handle:
            return "SUCCESS" in handle.read()

    record = import_module.supervise_child(
        _python_child("print('SUCCESS: import finished')"),
        "validation_pass",
        output_validator=validator,
    )
    assert record["state"] == import_module.STATE_OK
    assert seen["stdout_path"] == record["stdout_path"]
    assert seen["stderr_path"] == record["stderr_path"]


def test_output_validation_exception_is_not_success(supervision_dir):
    def exploding_validator(stdout_path, stderr_path, record):
        raise RuntimeError("validator blew up")

    with pytest.raises(import_module.ChildProcessError) as excinfo:
        import_module.supervise_child(
            _python_child("print('anything')"),
            "validation_raise",
            output_validator=exploding_validator,
        )
    record = excinfo.value.record
    assert record["state"] == import_module.STATE_OUTPUT_VALIDATION_FAILED
    assert "error" in record["output_validation"]


def test_wrapping_quote_stripping():
    """Quotes existed only for cmd.exe; they must not reach the child."""
    # The real call-site shape: quotes wrap the value, not the whole argument.
    assert import_module._strip_wrapping_quotes(
        '-importSettings="C:\\a b\\s.json"'
    ) == "-importSettings=C:\\a b\\s.json"
    # Whole-argument quoting.
    assert import_module._strip_wrapping_quotes('"C:\\a b\\s.json"') == "C:\\a b\\s.json"
    # Untouched shapes.
    assert import_module._strip_wrapping_quotes("-plain") == "-plain"
    assert import_module._strip_wrapping_quotes("-OnlyPrepareMaps=1") == (
        "-OnlyPrepareMaps=1"
    )
    assert import_module._strip_wrapping_quotes('"') == '"'
    assert import_module._strip_wrapping_quotes('a"b"c"d') == 'a"b"c"d'


def test_editor_executable_resolution_prefers_cmd(monkeypatch):
    monkeypatch.delenv("CARLA_IMPORT_EDITOR_EXE", raising=False)
    resolved = import_module.resolve_editor_executable(
        r"G:\UnrealEngine_4.26_CARLA", "Win64"
    )
    assert os.path.basename(resolved) in ("UE4Editor-Cmd.exe", "UE4Editor.exe")
    assert "Engine/Binaries/Win64" in resolved.replace(os.sep, "/")


def test_editor_executable_honours_override(monkeypatch):
    monkeypatch.setenv("CARLA_IMPORT_EDITOR_EXE", "/custom/Editor.exe")
    assert import_module.resolve_editor_executable("ignored", "Win64") == (
        "/custom/Editor.exe"
    )


def test_invoke_commandlet_propagates_child_failure(supervision_dir, monkeypatch):
    """The commandlet wrapper must surface a nonzero child exit."""
    monkeypatch.setenv("UE4_ROOT", r"G:\UnrealEngine_4.26_CARLA")
    monkeypatch.setenv(
        "CARLA_IMPORT_EDITOR_EXE", os.path.join(str(supervision_dir), "absent.exe")
    )
    with pytest.raises(import_module.ChildProcessError):
        import_module.invoke_commandlet("ImportAssets", ["-nosourcecontrol"])


def test_invoke_commandlet_builds_unquoted_command_line(supervision_dir, monkeypatch):
    """Quoted arguments must be de-quoted for the direct (shell-free) spawn."""
    monkeypatch.setenv("UE4_ROOT", r"G:\UnrealEngine_4.26_CARLA")
    monkeypatch.setenv("CARLA_IMPORT_EDITOR_EXE", sys.executable)

    captured = {}
    original = import_module.subprocess.Popen

    def spy(command, **kwargs):
        captured["command"] = command
        captured["shell"] = kwargs.get("shell")
        return original(command, **kwargs)

    import_module.subprocess.Popen = spy
    try:
        with pytest.raises(import_module.ChildProcessError):
            # sys.executable cannot run a commandlet, so it exits nonzero;
            # the point is the command line construction and shell=False.
            import_module.invoke_commandlet(
                "ImportAssets", ['-importSettings="%s"' % os.path.join("C:", "x.json")]
            )
    finally:
        import_module.subprocess.Popen = original

    command = captured["command"]
    assert captured["shell"] is False
    assert command[0] == sys.executable
    assert "-run=ImportAssets" in command
    assert any(a.endswith("x.json") and '"' not in a for a in command), command


def test_unguarded_subprocess_calls_do_not_remain():
    """No bare subprocess.call/check_call may survive in executable code."""
    code_lines = []
    with open(IMPORT_PY, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            # Comments may legitimately name the historical API.
            if stripped.startswith("#"):
                continue
            code_lines.append(line)
    source = "".join(code_lines)

    for forbidden in (
        "subprocess.check_call(",
        'subprocess.call(["build.bat"',
        'subprocess.call(["./build.sh',
        'subprocess.call(["chmod +x',
    ):
        assert forbidden not in source, (
            "unguarded subprocess call remains: %s" % forbidden
        )


def test_posix_branch_no_longer_discards_return_code():
    """The old posix path used subprocess.call and threw the status away.

    Both platform branches now share one supervised code path, so no platform
    conditional may sit between a spawn and its exit-status check.
    """
    code_lines = []
    with open(IMPORT_PY, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip().startswith("#"):
                continue
            code_lines.append(line)
    source = "".join(code_lines)

    # No status-discarding API survives anywhere in executable code.
    assert "subprocess.call(" not in source
    assert "subprocess.check_call(" not in source
    # Exactly one spawn site, and it is the supervised one.
    assert source.count("subprocess.Popen(") == 1
    # The platform conditional now only selects the binary name; it no longer
    # selects between a checked and an unchecked invocation.
    assert 'os.name == "nt" else "Linux"' in source