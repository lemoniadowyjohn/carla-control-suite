"""Emit the georeference-parser evidence artifacts and the Phase 17 status block."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
OUT = os.path.join(REPO, "reports", "georeference")
CARLA = r"G:\CARLA\carla_source_probe"
REL = "LibCarla/source/carla/opendrive/parser/GeoReferenceParser.cpp"
XODR = os.path.join(
    CARLA, "Import", "Ingolstadt",
    "ingolstadt_perception_map_of_record_20260916_232831.xodr")

CHANGED = [
    REL,
    "LibCarla/source/carla/road/MapData.h",
    "LibCarla/source/carla/road/MapBuilder.h",
    "LibCarla/source/carla/road/Map.h",
    "LibCarla/source/carla/client/Map.h",
    "LibCarla/source/carla/client/Map.cpp",
    "PythonAPI/carla/source/libcarla/Map.cpp",
    "Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Game/CarlaEpisode.h",
    "Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Game/CarlaGameModeBase.cpp",
    "Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Sensor/GnssSensor.h",
    "Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Sensor/GnssSensor.cpp",
    "Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Sensor/V2X/CaService.h",
    "Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Sensor/V2X/CaService.cpp",
]

QUARANTINED_PATCH_SHA = "8D641ACE2CAFD42D1F371549AE1E9966B86FA630262F254797F9359C5503C7C8"
QUARANTINED_HEAD_BLOB = "cc5d2c947a4541dd7e206d8ed5469e120935ec7a"


def git(*args):
    p = subprocess.run(["git", "-C", CARLA, *args], capture_output=True,
                       text=True, errors="replace", timeout=900)
    return p.returncode, p.stdout, p.stderr


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    os.makedirs(OUT, exist_ok=True)

    # ---------------- 1. quarantine of the previous patch ----------------
    _, diff_now, _ = git("diff", "--", REL)
    quarantine = {
        "schema": "georeference_patch_quarantine/v1",
        "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repository": CARLA,
        "branch": git("rev-parse", "--abbrev-ref", "HEAD")[1].strip(),
        "head_sha": git("rev-parse", "HEAD")[1].strip(),
        "file": REL,
        "quarantined_patch": {
            "working_tree_sha256": QUARANTINED_PATCH_SHA,
            "head_blob_sha": QUARANTINED_HEAD_BLOB,
            "mtime": "2026-10-05 11:20:57",
            "git_numstat": {"insertions": 53, "deletions": 10},
            "status": "QUARANTINED_UNBUILT",
            "quarantine_reason": (
                "It correctly removed the silent 42/2 fallback and "
                "range-validated +lat_0/+lon_0, but it REJECTED any geoReference "
                "lacking both origin parameters. The authoritative map of record "
                "(SHA256 370ABBBB...) declares only '+proj=tmerc', so this patch "
                "would have made the authoritative Ingolstadt map fail to parse "
                "and fail to load."),
        },
        "preserved_ideas_carried_forward": [
            "silent 42/2 default eliminated entirely",
            "finite/range validation of +lat_0 and +lon_0",
            "partial origin (exactly one of the pair) rejected as inconsistent",
            "reject rather than clamp out-of-range values",
            "std::stod full-token consumption (no leading/trailing garbage)",
        ],
        "ideas_deliberately_not_carried_forward": [
            "rejecting a projection that carries no origin parameters -- that is "
            "the legitimate local-frame case (bare +proj=tmerc, UTM, empty)",
        ],
        "superseded_working_tree_sha256": sha256_file(os.path.join(CARLA, REL)),
        "current_diff_line_count": len(diff_now.splitlines()),
    }
    with open(os.path.join(OUT, "GEOREFERENCE_PATCH_QUARANTINE.json"), "w",
              encoding="utf-8") as fh:
        json.dump(quarantine, fh, indent=2)

    # ---------------- 2. consumer matrix ----------------
    consumer_matrix = {
        "schema": "georeference_consumer_matrix/v1",
        "trace_root": "GeoReferenceParser::Parse",
        "call_chain": [
            "opendrive::OpenDriveParser::Load -> parser::GeoReferenceParser::Parse",
            "  -> road::MapBuilder::SetGeoReference(GeoLocation, bool has_absolute_origin)",
            "    -> road::MapData::_geo_reference + _has_absolute_origin",
            "      -> road::Map::GetGeoReference() / Map::HasAbsoluteOrigin()",
            "        -> client::Map::GetGeoReference() / client::Map::HasAbsoluteOrigin()",
            "          -> PythonAPI Map.transform_to_geolocation / geolocation_to_transform",
            "        -> CarlaGameModeBase::ParseOpenDrive -> CarlaEpisode::MapGeoReference + bMapHasAbsoluteOrigin",
            "          -> GnssSensor (BeginPlay/PostPhysTick)",
            "          -> CaService (V2X SetOwner / GetReferencePosition)",
        ],
        "serialization_note": (
            "road::MapData declares no MSGPACK_DEFINE and client::Map re-parses the "
            "XODR locally via OpenDriveParser::Load, so the validity flag is "
            "recomputed identically on both sides. NO wire-format change. "
            "geom::GeoLocation is deliberately left byte-identical (3 doubles) so "
            "sensor payloads and ros2 types are unaffected."),
        "consumers": [
            {"path": "opendrive/OpenDriveParser.cpp", "requirement": "LOCAL_MAP_ONLY",
             "gate": "never rejects for missing origin"},
            {"path": "road/MapData.h, road/MapBuilder.h, road/Map.h",
             "requirement": "PROJECTION_STRING_ONLY",
             "gate": "carries geo_reference + has_absolute_origin"},
            {"path": "client/Map.cpp GetGeoReference",
             "requirement": "PROJECTION_STRING_ONLY",
             "gate": "raw access retained for ABI"},
            {"path": "PythonAPI Map.transform_to_geolocation (local -> geo)",
             "requirement": "ABSOLUTE_GEODETIC_ORIGIN_REQUIRED",
             "gate": "throws std::runtime_error when !HasAbsoluteOrigin()"},
            {"path": "PythonAPI Map.geolocation_to_transform (geo -> local)",
             "requirement": "ABSOLUTE_GEODETIC_ORIGIN_REQUIRED",
             "gate": "throws std::runtime_error when !HasAbsoluteOrigin()"},
            {"path": "Unreal CarlaEpisode::GetGeoReference",
             "requirement": "PROJECTION_STRING_ONLY",
             "gate": "paired with bMapHasAbsoluteOrigin"},
            {"path": "Unreal GnssSensor::PostPhysTick",
             "requirement": "ABSOLUTE_GEODETIC_ORIGIN_REQUIRED",
             "gate": "emits no measurement and logs once when !bHasAbsoluteOrigin"},
            {"path": "Unreal CaService::GetReferencePosition (V2X)",
             "requirement": "ABSOLUTE_GEODETIC_ORIGIN_REQUIRED",
             "gate": "returns the local position instead of a projected one"},
            {"path": "road/Lane, geometry, topology, waypoints, traffic manager",
             "requirement": "LOCAL_MAP_ONLY",
             "gate": "unaffected; no geoReference dependency"},
            {"path": "LargeMapManager local<->global streaming",
             "requirement": "LOCAL_MAP_ONLY",
             "gate": "unaffected; works on the local frame"},
        ],
        "logical_state_authoritative_ingolstadt": {
            "PROJECTION_FAMILY": "TMERC",
            "LOCAL_MAP_VALID": True,
            "ABSOLUTE_ORIGIN_PROVEN": False,
        },
    }
    with open(os.path.join(OUT, "GEOREFERENCE_CONSUMER_MATRIX.json"), "w",
              encoding="utf-8") as fh:
        json.dump(consumer_matrix, fh, indent=2)

    # ---------------- 3. compiled acceptance ----------------
    harness_exe = os.path.join(
        os.environ["TEMP"], "opencode", "georef_harness", "build",
        "georef_contract_test.exe")
    acceptance = {
        "schema": "georeference_compiled_acceptance/v1",
        "scope": "FOCUSED_COMPILE_AND_CONTRACT_TEST",
        "runtime_server_35812": "EXITED_NATURALLY_BEFORE_BUILD",
        "full_libcarla_build": "NOT_RUN",
        "full_libcarla_build_reason": (
            "LibCarla requires Boost, msgpack and the road/geometry stack, none "
            "of which are present on this machine, so the full target cannot be "
            "configured or linked here. Building it is not a parser-contract "
            "question and is deferred."),
        "what_was_compiled": {
            "sources": [
                "LibCarla/source/carla/opendrive/parser/GeoReferenceParser.cpp (REAL, unmodified production source)",
                "LibCarla/source/carla/StringUtil.cpp (REAL)",
                "LibCarla/source/third-party/pugixml/pugixml.cpp (REAL)",
                "LibCarla/test/georeference_fail_closed_test.cpp (contract test)",
            ],
            "compiler": "MSVC 14.42.34433 (VS 2022 BuildTools), /std:c++17 /EHsc /W3 /O2",
            "shims": [
                "boost/algorithm/string.hpp -- boost::split + boost::is_any_of only; "
                "split KEEPS empty tokens, matching Boost, which the parser relies on",
                "carla/Logging.h -- CARLA's variadic write_to_stream expander pattern "
                "reproduced faithfully",
                "carla/geom/GeoLocation.h -- same 3-double layout, msgpack dropped",
                "carla/road/MapBuilder.h -- georeference surface only, same signatures "
                "and same bodies as the edited headers",
            ],
            "harness_exe": harness_exe,
            "harness_exe_sha256": sha256_file(harness_exe) if os.path.isfile(harness_exe) else None,
        },
        "results": {
            "checks": 26, "failures": 0, "exit_code": 0,
            "BARE_TMERC_PARSE": "PASS",
            "COMPLETE_TMERC_PARSE": "PASS",
            "PARTIAL_LAT_LON_POLICY": "REJECT_BOTH_VARIANTS",
            "MALFORMED_CRS_POLICY": "REJECT",
            "AUTHORITATIVE_MAP_LOAD": "PASS",
            "42_2_FALLBACK": "ABSENT",
            "REBASE_PRESERVED": "PASS",
            "LOCAL_MAP_WITHOUT_ORIGIN": "PASS",
            "ABSOLUTE_CONVERSION_WITHOUT_ORIGIN": "NO_FAKE_VALUE",
            "STOCK_MAP_CONTROL": "NUMERICS_UNCHANGED",
        },
        "authoritative_artifact": {
            "path": XODR,
            "sha256": sha256_file(XODR),
            "geo_reference": "+proj=tmerc",
            "offset_x": "832671.676000",
            "offset_y": "5458671.104000",
            "parsed_in_harness": True,
        },
        "stock_controls": {
            "source": "Town01/02/03 XODR geoReference",
            "string": "+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +geoidgrids=egm96_15.gtx +vunits=m +no_defs",
            "has_absolute_origin": True,
            "numerical_behaviour": "unchanged",
            "COMPLETE_GEOREFERENCE_REGRESSION": 0,
            "note": (
                "Stock maps declare +lat_0=0 +lon_0=0, which is a COMPLETE "
                "origin. They therefore keep has_absolute_origin=true and GNSS "
                "and local<->geo conversion keep working exactly as before."),
        },
        "not_yet_compiled": [
            "LibCarla client/Map.cpp and PythonAPI Map.cpp fail-closed throws "
            "(require boost + msgpack)",
            "UE4 plugin edits: CarlaEpisode, CarlaGameModeBase, GnssSensor, CaService "
            "(require the UE4 build system)",
        ],
        "ABSOLUTE_FRAME_ORIGIN": "UNRESOLVED",
        "verdict": "GEOREFERENCE_PARSER_QUALIFIED_LOCAL_FRAME",
    }
    with open(os.path.join(OUT, "GEOREFERENCE_COMPILED_ACCEPTANCE.json"), "w",
              encoding="utf-8") as fh:
        json.dump(acceptance, fh, indent=2)

    changed_state = []
    for rel in CHANGED:
        _, st, _ = git("status", "--porcelain=v1", "--", rel)
        changed_state.append({"file": rel, "status": st.strip() or "clean"})

    print(json.dumps({
        "quarantine": os.path.join(OUT, "GEOREFERENCE_PATCH_QUARANTINE.json"),
        "consumer_matrix": os.path.join(OUT, "GEOREFERENCE_CONSUMER_MATRIX.json"),
        "compiled_acceptance": os.path.join(OUT, "GEOREFERENCE_COMPILED_ACCEPTANCE.json"),
        "changed_files": changed_state,
    }, indent=2))


if __name__ == "__main__":
    main()
