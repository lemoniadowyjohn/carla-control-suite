"""Tests for tools/ue4_import_log_analysis.py.

The parser is the authoritative before/after measurement instrument for the
import hardening work, so it is tested against *real* log fragments copied
verbatim from G:\\CARLA\\build_logs\\ingolstadt_import_20261004T001601Z.log.

The most important tests here are the ones that catch measurement bugs that
would otherwise silently produce a confident, wrong number:

  * the timestamp parser must anchor after the date, or every duration in the
    report collapses to zero;
  * category counts must sum back to the warning total;
  * completion must not be inferred from a "Success" substring seen mid-log.
"""
from __future__ import annotations

import pytest

from tools.ue4_import_log_analysis import (
    analyze_lines,
    classify,
    parse_timestamp,
    percentile,
)

# --- verbatim fragments from the real baseline log -----------------------

STALL = ("[2026.10.04-17.03.26:285][  0]LogStaticMesh: Display: Main thread "
         "blocked for 1882.686s for async distance field build of "
         "Ingolstadt_Tile_6_7_Building_Antalya to complete!  This can happen "
         "if the mesh is rebuilt excessively.")

TANGENT = ("[2026.10.04-17.03.35:198][  0]LogStaticMesh: Warning: "
           "Ingolstadt_Tile_6_8_Building_St__Matthus has degenerate tangent "
           "bases which will result in incorrect shading.  MikkTSpace relies on "
           "tangent bases and may result in mesh corruption, consider disabling "
           "this option.")

BINORMAL = ("[2026.10.04-17.03.35:540][  0]LogStaticMesh: Warning: "
            "Ingolstadt_Tile_6_8_Building_St__Matthus has some nearly zero "
            "bi-normals which can create some issues. (Tolerance of 1E-4)")

SMOOTHING = ("[2026.10.04-17.03.27:700][  0]FBXImport: Warning: No smoothing "
             "group information was found in this FBX scene.  Please make sure "
             "to enable the 'Export Smoothing Groups' option in the FBX "
             "Exporter plug-in before exporting the file.")

DUPID = ("[2026.10.04-00.19.37:881][  0]LogAssetManager: Warning: Found "
         "Duplicate PrimaryAssetID Map:/Game/Carla/Maps/BaseLargeMap/LargeMap, "
         "this must be resolved before saving. Path "
         "/Game/Maps/BaseLargeMap/LargeMap.LargeMap is replacing path "
         "/Game/Maps/Town11/Town11.Town11")

DUPID_TILES = ("[2026.10.04-00.19.38:120][  0]LogAssetManager: Warning: Found "
               "Duplicate PrimaryAssetID Map:/Game/Carla/Maps/TestMaps/EmptyMap, "
               "this must be resolved before saving. Path "
               "/Game/Carla/Maps/TestMaps/EmptyMap.EmptyMap is replacing path "
               "/Game/Maps/Town11/Town11_Tile_0_0.Town11_Tile_0_0")

CONSOLE = ("[2026.10.04-01.13.40:433][  0]LogConsoleManager: Warning: "
           "Performance warning: Console object named "
           "'r.GenerateMeshDistanceFields' shows many (500) "
           "FindConsoleObject() calls (consider caching e.g. using static)")

MISSINGOBJ = ("[2026.10.04-00.20.11:000][  0]LogUObjectGlobals: Warning: Failed "
              "to find object 'Object "
              "/Game/Ingolstadt/Maps/Ingolstadt/Ingolstadt_Tile_10_6_Building0."
              "Ingolstadt_Tile_10_6_Building0'")

SHADER_WORKER = ("[2026.10.04-16.55.33:974][  0]LogShaderCompilers: Display: "
                 "Worker (5/9): shaders left to compile 1")

DDC = ("[2026.10.04-00.18.14:319][  0]LogDerivedDataCache: Display: Loaded Boot "
       "cache: ../../../../CARLA/carla_source_probe/Unreal/CarlaUE4/"
       "DerivedDataCache/Boot.ddc")

# Verbatim from the real log (line 814). Note the shape: the verbosity token is
# "Display" and "Success - 0 error(s)" is the *message*. An earlier hand-written
# fixture wrongly used "LogPython: Success - ..." which is not the real shape.
SUCCESS = ("[2026.10.04-00.22.18:509][  0]LogInit: Display: Success - 0 "
           "error(s), 41 warning(s)")

ALL_FRAGMENTS = [STALL, TANGENT, BINORMAL, SMOOTHING, DUPID, DUPID_TILES,
                 CONSOLE, MISSINGOBJ, SHADER_WORKER, DDC, SUCCESS]


# --- timestamp parsing ---------------------------------------------------
class TestTimestamp:
    def test_anchors_after_date(self):
        # Regression guard: an unanchored pattern matches "20.26.10" inside the
        # date and makes every stamp in one log identical, zeroing durations.
        assert parse_timestamp("2026.10.04-00.18.06:237") == 0 * 3600 + 18 * 60 + 6
        assert parse_timestamp("2026.10.04-17.03.54:710") == 17 * 3600 + 3 * 60 + 54

    def test_two_stamps_differ(self):
        a = parse_timestamp("2026.10.04-00.18.06:237")
        b = parse_timestamp("2026.10.04-17.03.54:710")
        assert b - a == 60348

    def test_garbage_returns_zero(self):
        assert parse_timestamp("not-a-timestamp") == 0.0


# --- percentiles ---------------------------------------------------------
class TestPercentile:
    def test_known_values(self):
        xs = [1.0, 2.0, 3.0, 4.0]
        assert percentile(xs, 0) == 1.0
        assert percentile(xs, 100) == 4.0
        assert percentile(xs, 50) == pytest.approx(2.5)

    def test_single_and_empty(self):
        assert percentile([5.0], 95) == 5.0
        assert percentile([], 95) == 0.0


# --- classification ------------------------------------------------------
class TestClassify:
    @pytest.mark.parametrize("line,expected", [
        (STALL, "DISTANCE_FIELD"),
        (TANGENT, "TANGENT_BINORMAL"),
        (BINORMAL, "TANGENT_BINORMAL"),
        (SMOOTHING, "SMOOTHING_GROUP"),
        (DUPID, "ASSET_MANAGER_DUPLICATE"),
        (DUPID_TILES, "ASSET_MANAGER_DUPLICATE"),
        (CONSOLE, "CONSOLE_LOOKUP_PERFORMANCE"),
        (MISSINGOBJ, "ASSET_RESOLUTION"),
        (SHADER_WORKER, "SHADER_WORKER"),
        (DDC, "DDC"),
    ])
    def test_real_fragments_classify(self, line, expected):
        msg = line.split("]: ", 1)[-1]
        cat = line.split("]", 2)[2].split(":")[0]
        assert classify(cat, "Warning", msg) == expected

    def test_fatal_wins_over_everything(self):
        assert classify("LogWindows", "Fatal",
                        "Fatal error: something") == "FATAL"

    def test_distance_field_is_display_not_warning(self):
        # the stall message is Display verbosity but must still be extracted
        m = analyze_lines([STALL])
        assert m.distance_field_stats["count"] == 1
        assert m.distance_field_stats["max_seconds"] == pytest.approx(1882.686)


# --- extraction ----------------------------------------------------------
class TestExtraction:
    def test_distance_field_block(self):
        m = analyze_lines([STALL])
        assert len(m.distance_field_blocks) == 1
        e = m.distance_field_blocks[0]
        assert e["mesh"] == "Ingolstadt_Tile_6_7_Building_Antalya"
        assert e["seconds"] == pytest.approx(1882.686)
        assert e["timestamp_seconds"] == parse_timestamp("2026.10.04-17.03.26:285")

    def test_tangent_and_binormal_meshes(self):
        m = analyze_lines([TANGENT, BINORMAL])
        assert m.tangent_meshes == ["Ingolstadt_Tile_6_8_Building_St__Matthus"]
        assert m.binormal_meshes == ["Ingolstadt_Tile_6_8_Building_St__Matthus"]

    def test_smoothing_count(self):
        assert analyze_lines([SMOOTHING]).smoothing_warning_count == 1

    def test_duplicate_primary_asset_id_pairs(self):
        m = analyze_lines([DUPID, DUPID_TILES])
        assert len(m.duplicate_primary_asset_ids) == 2
        first = m.duplicate_primary_asset_ids[0]
        assert first["primary_asset_id"] == \
            "Map:/Game/Carla/Maps/BaseLargeMap/LargeMap"
        assert first["replacing_path"] == \
            "/Game/Maps/BaseLargeMap/LargeMap.LargeMap"
        assert first["replaced_path"] == "/Game/Maps/Town11/Town11.Town11"
        second = m.duplicate_primary_asset_ids[1]
        assert second["primary_asset_id"] == \
            "Map:/Game/Carla/Maps/TestMaps/EmptyMap"
        assert second["replaced_path"].startswith("/Game/Maps/Town11/Town11_Tile_0_0")

    def test_console_lookup_extraction(self):
        m = analyze_lines([CONSOLE])
        assert m.console_lookup_warnings == [
            {"name": "r.GenerateMeshDistanceFields", "count": 500,
             "timestamp": "2026.10.04-01.13.40:433"}]

    def test_missing_object_extraction(self):
        m = analyze_lines([MISSINGOBJ])
        assert m.missing_object_unique_paths == 1
        assert "Ingolstadt_Tile_10_6_Building0" in \
            list(m.missing_object_paths)[0]

    def test_shader_worker_denominator(self):
        m = analyze_lines([SHADER_WORKER])
        assert m.shader_worker_denominators == {9}
        assert m.shader_queue_last == 1


# --- invariants ----------------------------------------------------------
class TestInvariants:
    def test_categories_sum_to_warning_total(self):
        m = analyze_lines(ALL_FRAGMENTS)
        assert m.warning_total == m.category_totals_sum
        assert m.unclassified_warning_lines == 0

    def test_no_lossy_other_bucket(self):
        # every real fragment must land in a specific category, not OTHER
        m = analyze_lines([f for f in ALL_FRAGMENTS if "Failed" not in f
                           or "Duplicate" in f])
        assert m.category_counts["OTHER"] == 0

    def test_missing_object_is_not_silently_other(self):
        # 5,720 of these in the real log; they must be visible as a category
        m = analyze_lines([MISSINGOBJ] * 50)
        assert m.category_counts["ASSET_RESOLUTION"] == 50
        assert m.category_counts["OTHER"] == 0

    def test_unparsed_lines_counted(self):
        m = analyze_lines(["", "garbage line", STALL])
        assert m.total_lines == 3
        assert m.parsed_lines == 1
        assert m.unparsed_lines == 2


# --- terminal state ------------------------------------------------------
class TestTerminalState:
    def test_truncated_log_is_not_reported_complete(self):
        # Regression guard: this pipeline logs "Success - 0 error(s)" once per
        # imported tile (12 times in the real log, first at line 814 of 26,647),
        # so a bare substring match would wrongly declare the baseline import
        # complete when it in fact stops mid-stream.
        log = [
            "[2026.10.04-00.18.06:000][  0]LogInit: Display: Engine is initialized",
            SUCCESS,
        ] + [STALL] * 40
        m = analyze_lines(log)
        assert m.success_marker_line_number == 2
        assert m.terminal_state == "SUCCESS_MARKER_MIDSTREAM_NOT_TERMINAL"

    def test_success_at_end_is_completion(self):
        log = [STALL] + [SUCCESS]
        m = analyze_lines(log)
        assert m.terminal_state == "COMPLETED_SUCCESS"

    def test_success_is_display_verbosity_not_its_own_token(self):
        m = analyze_lines([SUCCESS])
        assert m.parsed_lines == 1
        assert m.verbosity_counts.get("Display") == 1
        assert m.terminal_state == "COMPLETED_SUCCESS"

    def test_no_marker_at_all_is_truncated(self):
        m = analyze_lines([STALL, TANGENT])
        assert m.terminal_state == "TRUNCATED_NO_TERMINATION_MARKER"

    def test_fatal_wins(self):
        log = [STALL,
               "[2026.10.04-00.19.00:000][  0]LogWindows: Error: Fatal error: boom",
               "[2026.10.04-00.19.01:000][  0]LogPython: Success - 0 error(s)"]
        m = analyze_lines(log)
        assert m.terminal_state == "FAILED_FATAL"


# --- percentiles over the real stall distribution -----------------------
class TestRealStallDistribution:
    def test_p95_over_known_set(self):
        xs = [2807.558, 2573.217, 2244.255, 1935.085, 1910.292, 1882.686,
              1881.549, 1851.614, 1824.995, 1763.606]
        p95 = percentile(xs, 95)
        assert p95 > 1763.606
        assert p95 <= 2807.558

    def test_stall_counts(self):
        # 1882.686 / 1435.126 / 25.349 / 20.974 -> all four exceed 10 s,
        # two exceed 60 s, two exceed 300 s.
        log = [STALL,
               STALL.replace("1882.686", "1435.126"),
               STALL.replace("1882.686", "25.349"),
               STALL.replace("1882.686", "20.974")]
        m = analyze_lines(log)
        s = m.distance_field_stats
        assert s["count"] == 4
        assert s["over_10s"] == 4
        assert s["over_60s"] == 2
        assert s["over_300s"] == 2