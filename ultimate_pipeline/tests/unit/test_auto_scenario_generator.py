# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/scenarios/auto_scenario_generator.py.

Live via main_pipeline.py and stage_09_tiling.py. Zero prior test
coverage. No bugs found -- simple, straightforward, no gate/safety logic.
"""
from __future__ import annotations

import json
import random

from ultimate_pipeline.scenarios.auto_scenario_generator import AutoScenarioGenerator


def test_empty_graph_returns_no_scenarios(tmp_path):
    paths = AutoScenarioGenerator.generate_from_graph({}, 3, str(tmp_path))
    assert paths == []


def test_generates_requested_number_of_scenario_files(tmp_path):
    graph = {
        "tile_0_0.xodr": {"neighbors": ["tile_0_1.xodr"]},
        "tile_0_1.xodr": {"neighbors": ["tile_0_0.xodr"]},
    }
    paths = AutoScenarioGenerator.generate_from_graph(graph, 5, str(tmp_path))
    assert len(paths) == 5
    for p in paths:
        assert p.endswith(".json")


def test_scenario_uses_a_real_neighbor_as_target(tmp_path):
    random.seed(42)
    graph = {
        "tile_0_0.xodr": {"neighbors": ["tile_0_1.xodr"]},
        "tile_0_1.xodr": {"neighbors": ["tile_0_0.xodr"]},
    }
    paths = AutoScenarioGenerator.generate_from_graph(graph, 10, str(tmp_path))
    for p in paths:
        cfg = json.loads(open(p, encoding="utf-8").read())
        assert cfg["target_tile"] in graph[cfg["start_tile"]]["neighbors"] + [cfg["start_tile"]]


def test_isolated_tile_becomes_a_local_only_scenario(tmp_path):
    graph = {"tile_9_9.xodr": {"neighbors": []}}
    paths = AutoScenarioGenerator.generate_from_graph(graph, 1, str(tmp_path))
    cfg = json.loads(open(paths[0], encoding="utf-8").read())
    assert cfg["start_tile"] == "tile_9_9.xodr"
    assert cfg["target_tile"] == "tile_9_9.xodr"


def test_scenario_config_has_expected_fields(tmp_path):
    graph = {"tile_0_0.xodr": {"neighbors": []}}
    paths = AutoScenarioGenerator.generate_from_graph(
        graph, 1, str(tmp_path), scenario_prefix="myscenario"
    )
    cfg = json.loads(open(paths[0], encoding="utf-8").read())
    assert cfg["id"] == "myscenario_0"
    assert 0 <= cfg["seed"] < 2**31
    assert cfg["traffic_density"] in ("low", "medium", "high")
    assert cfg["weather"] in ("clear", "rain", "hard_rain", "fog")


def test_creates_out_dir_if_missing(tmp_path):
    out_dir = tmp_path / "nested" / "scenarios"
    graph = {"tile_0_0.xodr": {"neighbors": []}}
    AutoScenarioGenerator.generate_from_graph(graph, 1, str(out_dir))
    assert out_dir.is_dir()
