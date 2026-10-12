"""Regression tests for the UE cook terminal classifier (GAP-049 L).

The 2026-10-11 cook died with an explicit UE fatal
(SavePackageUtilities.cpp:527 "Could not write to ...T_Fabric_15_R.ubulk!")
and must classify SAVE_PACKAGE_WRITE_FAILURE -- never silent, never unknown.
"""

from __future__ import annotations

from tools.cook_diagnostics.cook_terminal_classifier import classify_terminal

# Verbatim terminal excerpt from GAP049_COOK_DIAG_RUN_20261011_125615.
FABRIC_UBULK_LOG = """\
LogCook: Display: Cooked packages 3159 Packages Remain 399 Total 3558
LogCook: Display: Cook Diagnostics: OpenFileHandles=3559, VirtualMemory=6474MiB
LogThreadingWindows: Error: Runnable thread TaskGraphThreadNP 2 crashed.
LogWindows: Error: === Critical error: ===
LogWindows: Error: Fatal error: [File:G:/UnrealEngine_4.26_CARLA/Engine/Source/Runtime/CoreUObject/Private/UObject/SavePackage/SavePackageUtilities.cpp] [Line: 527]
LogWindows: Error: Could not write to G:/CARLA/cook_out/Ingolstadt/CarlaUE4/Content/Carla/Static/Pedestrian/Materials/MH_microdetail/T_Fabric_15_R.ubulk!
LogWindows: Error: Crash in runnable thread TaskGraphThreadNP 2
"""


def test_fabric_ubulk_regression_is_save_package_write_failure() -> None:
    out = classify_terminal(FABRIC_UBULK_LOG)
    assert out["class"] == "SAVE_PACKAGE_WRITE_FAILURE"
    assert any("T_Fabric_15_R.ubulk" in e for e in out["evidence"])
    assert out["class"] not in ("SILENT_HANG", "UNKNOWN_EXPLICIT")


def test_bare_savepackage_line_is_not_a_proven_write_failure() -> None:
    out = classify_terminal("LogWindows: Error: Fatal error: [File:X/SavePackageUtilities.cpp] [Line: 527]\n")
    # Fatal error present -> UE_FATAL_OTHER, but NOT a proven write failure.
    assert out["class"] == "UE_FATAL_OTHER"


def test_runnable_thread_crash_without_write_is_ue_fatal_other() -> None:
    out = classify_terminal("LogWindows: Error: Fatal error: Runnable thread TaskGraphThreadNP 7 crashed.")
    assert out["class"] == "UE_FATAL_OTHER"


def test_assertion_failed_is_ue_fatal_other() -> None:
    out = classify_terminal("LogWindows: Error: Assertion failed: IsValid(Index) [File:Dump.cpp] [Line: 12]")
    assert out["class"] == "UE_FATAL_OTHER"


def test_lowlevelfatal_is_ue_fatal_other() -> None:
    out = classify_terminal("LowLevelFatalError [File:Unknown] [Line: 1] Unhandled Exception")
    assert out["class"] == "UE_FATAL_OTHER"


def test_createfile_failed_is_storage_failure() -> None:
    out = classify_terminal("LogWindows: Error: CreateFile failed for 'G:/out/x.ubulk' with error 112.")
    assert out["class"] == "STORAGE_FAILURE"


def test_shader_oom_context() -> None:
    out = classify_terminal("ShaderCompileWorker: Ran out of memory allocating 2GB for shader compile.")
    assert out["class"] == "SHADER_COMPILER_OOM"


def test_bare_oom_without_shader_context_is_not_overclaimed() -> None:
    # A lone memory warning with no fatal/crash marker proves no terminal
    # class; mapping it to UE_FATAL_OTHER would be fabrication.
    out = classify_terminal("LogMemory: Warning: Ran out of memory.")
    assert out["class"] == "UNKNOWN_EXPLICIT"


def test_timeout_without_terminal_error() -> None:
    out = classify_terminal("LogCook: Display: Cooked packages 100 Packages Remain 3000",
                            process_alive=False, timed_out=True)
    assert out["class"] == "TIMEOUT"


def test_package_stall_vs_silent_hang() -> None:
    stalled = classify_terminal("LogCook: Display: Cooked packages 100 Packages Remain 3000",
                                process_alive=True, progress_ceased=True,
                                log_quiescent=False)
    assert stalled["class"] == "PACKAGE_STALL"
    silent = classify_terminal("LogCook: Display: Cooked packages 100 Packages Remain 3000",
                               process_alive=True, progress_ceased=True,
                               log_quiescent=True, os_crash_event=False)
    assert silent["class"] == "SILENT_HANG"


def test_silent_hang_requires_all_conditions() -> None:
    # Terminal error present -> never silent, even if quiescent.
    out = classify_terminal(FABRIC_UBULK_LOG, process_alive=True,
                            progress_ceased=True, log_quiescent=True)
    assert out["class"] == "SAVE_PACKAGE_WRITE_FAILURE"
    # OS crash event + quiescence -> storage failure, not silent.
    out2 = classify_terminal("LogCook: Display: Cooked packages 100",
                             process_alive=True, progress_ceased=True,
                             log_quiescent=True, os_crash_event=True)
    assert out2["class"] == "STORAGE_FAILURE"


def test_empty_log_is_unknown_explicit() -> None:
    assert classify_terminal("")["class"] == "UNKNOWN_EXPLICIT"


def test_clean_success() -> None:
    out = classify_terminal("LogCook: Display: Cook completed successfully. Packages: 3558.")
    assert out["class"] == "CLEAN_SUCCESS"
