# ultimate_pipeline/scenarios/auto_scenario_generator.py

import os
import json
import random
from typing import Dict, List


class AutoScenarioGenerator:
    """
    Generate simple scenario configs from tile adjacency graph.

    Each scenario:
      - chooses a start tile
      - chooses a neighbor tile as 'target'
      - assigns a random seed and traffic density
      - optionally tags if it's near a roundabout (if you pass roundabout info later)
    """

    @staticmethod
    def generate_from_graph(
        adjacency_graph: Dict[str, Dict],
        num_scenarios: int,
        out_dir: str,
        scenario_prefix: str = "scenario",
    ) -> List[str]:
        os.makedirs(out_dir, exist_ok=True)

        tile_names = list(adjacency_graph.keys())
        if not tile_names:
            return []

        paths: List[str] = []

        for idx in range(num_scenarios):
            start_tile = random.choice(tile_names)
            neighbors = adjacency_graph[start_tile].get("neighbors", [])
            if neighbors:
                target_tile = random.choice(neighbors)
            else:
                target_tile = start_tile  # local-only scenario

            cfg = {
                "id": f"{scenario_prefix}_{idx}",
                "start_tile": start_tile,
                "target_tile": target_tile,
                "seed": random.randint(0, 2**31 - 1),
                "traffic_density": random.choice(["low", "medium", "high"]),
                "weather": random.choice(["clear", "rain", "hard_rain", "fog"]),
                # You can extend this later:
                # "prefer_roundabout": True/False, etc.
            }

            out_path = os.path.join(out_dir, f"{scenario_prefix}_{idx}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            paths.append(out_path)

        return paths
