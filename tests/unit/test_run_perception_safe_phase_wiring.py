# -*- coding: utf-8 -*-
"""Phase journal + crash bundle wiring in run_perception_safe (NEW-268 / section 17).

The capture runner is mostly CARLA-dependent, so what must hold without a
server is:

* diagnostics can never raise out of the run (a broken journal must not turn a
  healthy capture into a failure);
* the run boundary phases are actually emitted by main(), not just importable;
* an unexpected exception produces a crash bundle rather than only a
  stderr.log.
"""
from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.tools.run_perception_safe import _journal_record, write_crash_bundle
from ultimate_pipeline.perception.crash_bundle import REQUIRED_BUNDLE_FILES
from ultimate_pipeline.perception.phase_journal import PhaseJournal

SOURCE = Path(__file__).resolve().parents[2] / "ultimate_pipeline" / "tools" / "run_perception_safe.py"


def test_journal_record_is_a_noop_without_a_journal():
    _journal_record(None, "RUN_BEGIN", anything=1)  # must not raise


def test_journal_record_swallows_a_broken_journal():
    class _Broken:
        def record(self, phase, **fields):
            raise OSError("disk full")

    _journal_record(_Broken(), "RUN_BEGIN")  # must not raise


def test_journal_record_writes_when_the_journal_is_healthy(tmp_path):
    journal = PhaseJournal(tmp_path / "phase_journal.jsonl")
    _journal_record(journal, "MAP_LOAD_BEGIN", requested_town="Grid0828")
    _journal_record(journal, "MAP_LOAD_RETURN", map_name="Grid0828")
    journal.close()
    lines = (tmp_path / "phase_journal.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "MAP_LOAD_BEGIN" in lines[0]
    assert "Grid0828" in lines[1]


def test_runner_source_journals_the_run_boundary_phases():
    source = SOURCE.read_text(encoding="utf-8")
    for phase in (
        "RUN_BEGIN",
        "MAP_LOAD_BEGIN",
        "MAP_LOAD_RETURN",
        "CAPTURE_BEGIN",
        "CAPTURE_END",
        "FLUSH_BEGIN",
        "FLUSH_END",
        "TEARDOWN_BEGIN",
        "COMPLETE",
    ):
        assert f'"{phase}"' in source, f"missing phase journal entry: {phase}"
    assert "PhaseJournal(" in source
    assert source.index("PhaseJournal(") < source.index('"RUN_BEGIN"')


def test_runner_source_writes_a_crash_bundle_on_unexpected_exception():
    source = SOURCE.read_text(encoding="utf-8")
    assert "write_crash_bundle(" in source
    handler = source.index("except Exception as exc:")
    bundle = source.index("write_crash_bundle(")
    assert bundle > handler, "crash bundle must be written from the exception handler"
    assert "phase_journal_path=phase_journal_path" in source
    assert 'client_stderr_path=out_dir / "stderr.log"' in source


def test_runner_import_exposes_the_wired_helpers(tmp_path):
    import ultimate_pipeline.tools.run_perception_safe as runner

    assert callable(runner._journal_record)
    assert runner.write_crash_bundle is write_crash_bundle
    index = write_crash_bundle(tmp_path, reason="probe")
    assert index["complete"] is True
    assert set(index["present_files"]) >= set(REQUIRED_BUNDLE_FILES)
