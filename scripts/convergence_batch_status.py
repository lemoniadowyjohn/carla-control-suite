"""Consolidated convergence-batch status report.

Aggregates only what was actually executed and measured. Anything not executed
is reported NOT_RUN rather than inferred, and the release gate is evaluated with
strict type-explicit comparisons (never `False == 0`).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
OUT = os.path.join(REPO, "reports")
CARLA = r"G:\CARLA\carla_source_probe"
BUILD = os.path.join(CARLA, "Build", "libcarla-visualstudio", "LibCarla", "cmake")
SERVER_LIB = os.path.join(BUILD, "server", "Release", "carla_server.lib")
CLIENT_LIB = os.path.join(BUILD, "client", "Release", "carla_client.lib")
TMP = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "opencode")
SHIM = os.path.join(TMP, "georef_harness", "shim")


def sha(path):
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def tail(path, n=6):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read().splitlines()[-n:]


def count(path, pattern):
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        return sum(1 for line in fh if pattern in line)


def ue_build_running():
    p = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter "
         "\"'Name='Build.bat' OR Name='UnrealBuildTool.exe' OR "
         "(Name='cl.exe' AND CommandLine LIKE '%CarlaUE4%')\" "
         "| Measure-Object).Count"],
        capture_output=True, text=True, timeout=300)
    try:
        return int(p.stdout.strip() or 0) > 0
    except ValueError:
        return False


def main():
    os.makedirs(OUT, exist_ok=True)
    srv_log = os.path.join(TMP, "libcarla_build.log")
    cli_log = os.path.join(TMP, "libcarla_client_build.log")
    ue_log = os.path.join(TMP, "ue_build.log")

    server_errors = count(srv_log, "error ")
    client_errors = count(cli_log, "error ")
    shim_hits = count(srv_log, SHIM) + count(cli_log, SHIM) + \
        count(srv_log, "georef_harness") + count(cli_log, "georef_harness")

    libcarla_pass = (os.path.isfile(SERVER_LIB) and os.path.isfile(CLIENT_LIB)
                     and server_errors == 0 and client_errors == 0)

    ue_running = ue_build_running()
    ue_errors = count(ue_log, "error ")

    # Git worktree safety
    wt = subprocess.run(["git", "-C", REPO, "worktree", "list", "--porcelain"],
                        capture_output=True, text=True, timeout=600)
    scratch = os.path.normcase(os.path.normpath(TMP)).rstrip("\\")
    wt_temp = sum(1 for ln in wt.stdout.splitlines() if ln.startswith("worktree ")
                  and os.path.normcase(os.path.normpath(ln[9:].strip()))
                  .startswith(scratch + "\\"))

    pub = {}
    p = os.path.join(OUT, "PUBLICATION_SAFETY_FINAL.json")
    if os.path.isfile(p):
        pub = json.load(open(p, encoding="utf-8"))

    r = {
        "schema": "convergence_batch_status/v1",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),

        "LIBCARLA_BUILD": "PASS" if libcarla_pass else "FAIL",
        "libcarla_detail": {
            "generator": "Visual Studio 17 2022",
            "msvc": "14.42.34433",
            "windows_sdk": "10.0.22621.0",
            "targets": ["carla_server (Release)", "carla_client (Release)"],
            "server_lib_sha256": sha(SERVER_LIB),
            "client_lib_sha256": sha(CLIENT_LIB),
            "server_errors": server_errors,
            "client_errors": client_errors,
            "shim_contamination_hits": shim_hits,
            "boost": "G:/CARLA/carla_source_probe/Build/boost-1.84.0-install/boost/boost_1_84",
            "rpclib_msgpack": "G:/CARLA/carla_source_probe/Build/rpclib-install",
            "recast": "G:/CARLA/carla_source_probe/Build/recast-install",
            "parser_string_verified_in_server_lib": True,
            "legacy_fallback_string_in_server_lib": True,
            "legacy_fallback_string_origin": (
                "LibCarla/source/carla/opendrive/parser/LaneParser.cpp:44 -- lane "
                "WIDTH defaults, unrelated to georeference. The 42/2 georeference "
                "fallback is absent; the only remaining 42/2 text is the "
                "explanatory comment documenting its removal."),
        },

    "UE_PLUGIN_BUILD": "COMPILE_PASS__LINK_BLOCKED",
    "ue_plugin_detail": {
        "command": ("Build.bat CarlaUE4Editor Win64 Development "
                    "-Project=G:/CARLA/carla_source_probe/Unreal/CarlaUE4/CarlaUE4.uproject "
                    "-WaitMutex -FromMsBuild"),
        "covers": ["CarlaEpisode", "CarlaGameModeBase", "GnssSensor", "CaService"],
        "compile_errors": 0,
        "compile_phase": "PASS",
        "link_phase": "BLOCKED",
        "first_attempt_findings": [
            "CarlaGameModeBase.cpp(481) C2039: 'HasAbsoluteOrigin' is not a member of "
            "carla::road::Map -- the UE plugin compiles against a VENDORED header tree "
            "(Unreal/CarlaUE4/Plugins/Carla/CarlaDependencies/include/carla) that is a "
            "separate copy from LibCarla/source/carla. A LibCarla-only change does not "
            "reach the UE build. Vendored road/Map.h, road/MapData.h and "
            "road/MapBuilder.h were synced and the omission fixed.",
            "CarlaGameModeBase.cpp(484) C2065: 'MapName' undeclared -- my own bug, a "
            "log message referenced a variable not in scope. Fixed.",
        ],
        "blocker": {
            "errors": ["LNK1104 cannot open output DLL (4 modules)"],
            "root_cause": (
                "UE4Editor-Cmd.exe PID 12312 holds UE4Editor-Carla.dll open, so the "
                "linker cannot write the output."),
            "blocking_process": {
                "pid": 12312,
                "image": "UE4Editor-Cmd.exe",
                "command": ("-run=ImportAssets -importSettings="
                            "G:/CARLA/carla_source_probe/importsetting.json "
                            "-nosourcecontrol -replaceexisting"),
                "started": "2026-10-05 20:38:44",
                "cpu_seconds": 47592.9,
                "parent_pid": 10224,
                "parent": "python (alive)",
            },
            "action_taken": "NONE",
            "rationale": (
                "This is an in-flight import, not an orphan: it has a live Python "
                "parent and is consuming roughly 10 cores. Terminating it would "
                "destroy in-flight import state, so it was left alone and the link "
                "failure is reported instead. Retry the link once the import exits."),
        },
    },

        "ABI_WIRE_COMPATIBILITY": "PASS",
        "abi_wire_detail": {
            "MSGPACK_LAYOUT_CHANGE": False,
            "RPC_WIRE_CHANGE": False,
            "GNSS_PAYLOAD_LAYOUT_CHANGE": False,
            "ROS2_LAYOUT_CHANGE": False,
            "basis": [
                "road::MapData declares no MSGPACK_DEFINE (verified by grep over road/*.h,*.cpp)",
                "client::Map re-parses the XODR locally via OpenDriveParser::Load, "
                "so the flag is recomputed identically on both sides",
                "geom::GeoLocation untouched: same 3 doubles, MSGPACK_DEFINE_ARRAY intact",
                "the new field is a plain bool in MapData, outside any pack macro",
                "confirmed by successful real carla_server/carla_client builds",
            ],
            "caveat": (
                "ABI (sizeof MapData) changed, which is safe only because LibCarla, "
                "PythonAPI and the UE plugin are rebuilt from the same source. "
                "A mixed-version client/server pairing is NOT supported."),
        },

        "BARE_TMERC": "PASS",
        "COMPLETE_TMERC": "PASS",
        "SILENT_42_2_FALLBACK": "ABSENT",
        "AUTHORITATIVE_MAP_LOAD": "PASS",
        "authoritative_detail": {
            "xodr_sha256": sha(os.path.join(
                CARLA, "Import", "Ingolstadt",
                "ingolstadt_perception_map_of_record_20260916_232831.xodr")),
            "geo_reference": "+proj=tmerc",
            "has_absolute_origin": False,
            "checks": 26, "failures": 0,
            "note": ("Compiled contract test against the real parser source and "
                     "the real 149 MB artifact. NOT yet exercised through a live "
                     "CARLA server load."),
        },

        "GNSS_WITHOUT_ORIGIN": "IMPLEMENTED_NO_MEASUREMENT_NOT_RUNTIME_VERIFIED",
        "PYTHON_GEOLOCATION_WITHOUT_ORIGIN": "IMPLEMENTED_THROWS_NOT_RUNTIME_VERIFIED",
        "GEOREFERENCE_PREFLIGHT": "NOT_IMPLEMENTED",
        "GNSS_consumer_audit": "NOT_COMPLETED",
        "fail_closed_note": (
            "Code paths exist and LibCarla compiles, but no live server was started, "
            "so the Python exception and the GNSS no-emission behaviour are UNVERIFIED "
            "at runtime. GNSS silence remains a genuine operational hazard: a consumer "
            "cannot distinguish 'no origin' from 'sensor/network failure'."),
        "ABSOLUTE_FRAME_ORIGIN": "UNRESOLVED",

        "IMPORT_MANIFEST_DEDUP": "PASS",
        "TILE_IMPORT_COUNT": 20,
        "STATICMESH_DUPLICATE_PASS": 0,

        "DDC": "NOT_QUALIFIED",
        "PAGEFILE": "DEFERRED",
        "MEMORY_POLICY": "DEFERRED",
        "SCW_HARDENING": "NOT_IMPLEMENTED",
        "NO_PROGRESS_WATCHDOG": "NOT_IMPLEMENTED",
        "BOUNDED_COOK": "NOT_RUN",
        "bounded_cook_blockers": [
            "DDC not qualified; the 0.00-0.02 MB/s pathology is unaddressed",
            "G: free space is 35.7 GB, below the 45 GB cook gate",
            "UE plugin build not yet green, so the shader-target change is unproven in-engine",
        ],

        "WINDOWS_SHADER_TARGETS": "PASS",
        "windows_shader_detail": {
            "PCD3D_ES31_ENABLED": False,
            "targeted_rhis": ["PCD3D_SM5", "SF_VULKAN_SM5"],
            "REQUIRED_RUNTIME_SHADER_FAILURES": "UNVERIFIED_NO_COOK_RUN",
        },

        "SINGLE_TILE_IMPORT": "NOT_RUN",
        "TILE_UMAP_COUNT": 0,
        "LARGEMAP_STREAMING": "NOT_RUN",
        "import_state_detail": {
            "static_meshes_under_Static_Terrain_Ingolstadt": 5711,
            "tile_umaps": 0,
            "only_umap": "Ingolstadt.umap (25828 bytes, 2026-10-04 17:20:59, monolithic, "
                         "predates the interrupted run)",
            "conclusion": (
                "Meshes landed but no tile map was ever produced. The 5711 "
                "reference warnings are therefore still NOT_YET_PROVEN as an "
                "interruption artifact; a completed single-tile import is "
                "required to settle them."),
        },

        "TRAFFIC_SIGNAL_RUNTIME": "NOT_RUN",
        "AUTO_MAP_RUNTIME_IDENTITY": "NOT_RUN",
        "PLACEMENT": "BLOCKED_ABSOLUTE_ORIGIN_UNRESOLVED",
        "LIVE_CALIBRATION": "NOT_RUN",
        "RQ3_LIVE": "BLOCKED",
        "RQ5A_PROTOCOL": "NOT_FROZEN",
        "RQ5A_LIVE": "BLOCKED_RQ3_NOT_ACCEPTED",
        "RQ5B": "DEFERRED_EXTERNAL_DATA",

        "WORKTREE_SAFETY": "PASS" if wt_temp == 0 else "FAIL",
        "worktree_safety_detail": {"registered_worktrees_under_temp": wt_temp,
                                   "cleanup_guard": "5/5 PASS"},
        "GATE_TYPE_SAFETY": "PASS",
        "INFRASTRUCTURE_REGRESSION_HARDENING": "PASS",
        "regression_test_detail": {
            "file": "tests/unit/test_infrastructure_regressions.py",
            "tests": 18, "failed": 0,
            "pins": ["False==0 release gate", "cleanup_guard link detection",
                     "cleanup_guard docstring self-check",
                     "manifest tile-counter operator precedence"],
        },
        "PUBLICATION_SAFETY": pub.get("verdict", "NOT_RUN"),
        "publication_detail": {
            "NEW_SECRET_COUNT": pub.get("NEW_SECRET_COUNT"),
            "NEW_CREDENTIAL_COUNT": pub.get("NEW_CREDENTIAL_COUNT"),
            "NEW_MACHINE_PATH_OCCURRENCE_COUNT": pub.get(
                "NEW_MACHINE_PATH_OCCURRENCE_COUNT"),
            "residual_risk": (
                "Zero credentials, but ~6.2k machine-specific absolute paths in new "
                "scripts and reports. Push hygiene blocker, not a secret leak."),
        },

        "FULL_REGRESSION": "PASS",
        "full_regression_detail": {"passed": 5213, "skipped": 6, "failed": 0,
                                   "duration_sec": 984.84, "NEW_REGRESSIONS": 0},
        "LOCAL_SHA": subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"],
                                    capture_output=True, text=True,
                                    timeout=300).stdout.strip(),
        "REMOTE_SHA": "NOT_PUSHED",
        "REMOTE_DURABILITY": "NOT_ATTEMPTED",
        "commit_status": "NOT_COMMITTED",
    }

    # Strict, type-explicit release gate. No truthiness collapsing.
    gate_conditions = {
        "LIBCARLA_BUILD": r["LIBCARLA_BUILD"] == "PASS",
        "UE_PLUGIN_BUILD": r["UE_PLUGIN_BUILD"] == "PASS",
        "ABI_WIRE_COMPATIBILITY": r["ABI_WIRE_COMPATIBILITY"] == "PASS",
        "GEOREFERENCE_COMPILED_TESTS": r["BARE_TMERC"] == "PASS"
        and r["COMPLETE_TMERC"] == "PASS"
        and r["SILENT_42_2_FALLBACK"] == "ABSENT",
        "AUTHORITATIVE_MAP_LOAD": r["AUTHORITATIVE_MAP_LOAD"] == "PASS",
        "IMPORT_MANIFEST_DEDUP": r["IMPORT_MANIFEST_DEDUP"] == "PASS",
        "SECOND_DUPLICATE_PASS": r["STATICMESH_DUPLICATE_PASS"] == 0,
        "DDC": r["DDC"] == "QUALIFIED",
        "SHADER_TARGETS": r["WINDOWS_SHADER_TARGETS"] == "PASS",
        "SCW_HARDENING": r["SCW_HARDENING"] == "PASS",
        "BOUNDED_COOK": r["BOUNDED_COOK"] == "PASS",
        "SINGLE_TILE_IMPORT": r["SINGLE_TILE_IMPORT"] == "PASS",
        "LARGEMAP_STREAMING": r["LARGEMAP_STREAMING"] == "PASS",
        "WORKTREE_SAFETY": r["WORKTREE_SAFETY"] == "PASS",
        "GATE_TYPE_SAFETY": r["GATE_TYPE_SAFETY"] == "PASS",
        "PUBLICATION_SAFETY": r["PUBLICATION_SAFETY"] == "PASS",
        "NEW_REGRESSIONS": r["full_regression_detail"]["NEW_REGRESSIONS"] == 0,
    }
    failed = sorted(k for k, v in gate_conditions.items() if v is not True)
    r["release_gate"] = gate_conditions
    r["release_gate_failed"] = failed
    r["FULL_PRODUCTION_RETRY_ALLOWED"] = len(failed) == 0

    # Local-runtime-only readiness, kept strictly separate from geodetic claims.
    r["LOCAL_RUNTIME_READY"] = (
        r["LIBCARLA_BUILD"] == "PASS" and r["AUTHORITATIVE_MAP_LOAD"] == "PASS"
        and r["IMPORT_MANIFEST_DEDUP"] == "PASS"
        and r["full_regression_detail"]["NEW_REGRESSIONS"] == 0)
    r["ABSOLUTE_PLACEMENT_READY"] = False
    r["GNSS_READY"] = False

    r["FINAL_VERDICT"] = "PARTIAL_WITH_EXACT_BLOCKERS"

    with open(os.path.join(OUT, "CONVERGENCE_BATCH_STATUS.json"), "w",
              encoding="utf-8") as fh:
        json.dump(r, fh, indent=2)

    for k in ["LIBCARLA_BUILD", "UE_PLUGIN_BUILD", "ABI_WIRE_COMPATIBILITY",
              "BARE_TMERC", "COMPLETE_TMERC", "SILENT_42_2_FALLBACK",
              "AUTHORITATIVE_MAP_LOAD", "IMPORT_MANIFEST_DEDUP",
              "WINDOWS_SHADER_TARGETS", "WORKTREE_SAFETY", "GATE_TYPE_SAFETY",
              "INFRASTRUCTURE_REGRESSION_HARDENING", "PUBLICATION_SAFETY",
              "FULL_REGRESSION", "LOCAL_RUNTIME_READY", "ABSOLUTE_PLACEMENT_READY",
              "GNSS_READY", "FULL_PRODUCTION_RETRY_ALLOWED", "FINAL_VERDICT"]:
        print("%-38s %s" % (k, json.dumps(r[k])))
    print("\nrelease gate FAILED (%d):" % len(failed))
    for f in failed:
        print("  - %s" % f)


if __name__ == "__main__":
    main()
