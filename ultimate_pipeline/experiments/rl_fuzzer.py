"""
RL-based Map & Scenario Fuzzer

This module provides a controlled interface for applying stochastic or
policy-driven perturbations to OpenDRIVE maps and simulation parameters.

It is used to study:
- natural domain randomization
- robustness of perception models
- variability induced by map generation

The fuzzer samples perturbation actions and applies them to a real OpenDRIVE
map (driving-lane widths, arc curvature, object density), writing a new
content-addressed XODR. All randomness is seeded: the same seed reproduces
byte-identical output. The input map is never mutated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

# Hard bounds for accepted perturbation actions. Actions outside these ranges
# are rejected: the fuzzer must never produce a degenerate map.
LANE_WIDTH_SCALE_MIN = 0.5
LANE_WIDTH_SCALE_MAX = 2.0
CURVATURE_NOISE_MAX = 0.05
OBJECT_DENSITY_MIN = 0.25
OBJECT_DENSITY_MAX = 1.5
# Absolute curvature cap after noise application (recorded, not fatal).
MAX_ABS_CURVATURE = 0.25

DEFAULT_SAMPLE_RANGES: Dict[str, List[float]] = {
    "lane_width_scale": [0.9, 1.1],
    "curvature_noise": [0.0, 0.02],
    "object_density_scale": [0.8, 1.2],
}

_DRIVABLE_LANE_TYPES = {"driving", "bidirectional", "freeway", "parking", "restricted"}


class RLFuzzer:
    """
    Reinforcement-learning-style fuzzer for maps and scenarios.

    The fuzzer samples perturbation actions and applies them to maps,
    sensors, or simulation parameters. ``apply_to_map`` perturbs an OpenDRIVE
    file in place of a perturbation and writes a new, content-addressed copy.
    """

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.rng = random.Random(seed)
        self._episode_count = 0

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------
    def sample_action(self) -> Dict[str, Any]:
        """
        Sample a perturbation action.

        Returns
        -------
        Dict[str, Any]
            A dictionary describing a perturbation.
        """
        return {
            "lane_width_scale": self.rng.uniform(*DEFAULT_SAMPLE_RANGES["lane_width_scale"]),
            "curvature_noise": self.rng.uniform(*DEFAULT_SAMPLE_RANGES["curvature_noise"]),
            "object_density_scale": self.rng.uniform(*DEFAULT_SAMPLE_RANGES["object_density_scale"]),
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @staticmethod
    def validate_action(action: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and return the action; raise ValueError on out-of-bounds values."""
        if not isinstance(action, dict):
            raise ValueError("action must be a dict")
        try:
            width_scale = float(action["lane_width_scale"])
            noise = float(action["curvature_noise"])
            density = float(action["object_density_scale"])
        except KeyError as exc:
            raise ValueError(f"action missing key {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"action values must be numeric: {exc}") from exc
        if not (LANE_WIDTH_SCALE_MIN <= width_scale <= LANE_WIDTH_SCALE_MAX):
            raise ValueError(
                f"lane_width_scale {width_scale} outside [{LANE_WIDTH_SCALE_MIN}, {LANE_WIDTH_SCALE_MAX}]"
            )
        if not (0.0 <= noise <= CURVATURE_NOISE_MAX):
            raise ValueError(f"curvature_noise {noise} outside [0.0, {CURVATURE_NOISE_MAX}]")
        if not (OBJECT_DENSITY_MIN <= density <= OBJECT_DENSITY_MAX):
            raise ValueError(
                f"object_density_scale {density} outside [{OBJECT_DENSITY_MIN}, {OBJECT_DENSITY_MAX}]"
            )
        return action

    # ------------------------------------------------------------------
    # Perturbations
    # ------------------------------------------------------------------
    @staticmethod
    def _perturb_lane_widths(
        root: ET.Element, scale: float
    ) -> Dict[str, Any]:
        """Scale the a-coefficient of drivable-lane width records."""
        modified = 0
        clamped = 0
        for lane in root.findall(".//lane"):
            if (lane.get("type") or "").lower() not in _DRIVABLE_LANE_TYPES:
                continue
            for width in lane.findall("width"):
                try:
                    a = float(width.get("a", "0"))
                except (TypeError, ValueError):
                    continue
                new_a = a * scale
                if new_a <= 0.0:
                    clamped += 1
                    continue
                width.set("a", f"{new_a:.6f}")
                modified += 1
        return {"width_records_modified": modified, "width_records_dropped_nonpositive": clamped}

    def _perturb_curvature(self, root: ET.Element, noise: float) -> Dict[str, Any]:
        """Add signed bounded noise to arc geometry curvature."""
        modified = 0
        clamped = 0
        for geometry in root.findall(".//planView/geometry"):
            arc = geometry.find("arc")
            if arc is None:
                continue
            try:
                curvature = float(arc.get("curvature", "0"))
            except (TypeError, ValueError):
                continue
            new_curvature = curvature + self.rng.uniform(-noise, noise)
            if abs(new_curvature) > MAX_ABS_CURVATURE:
                clamped += 1
            arc.set("curvature", f"{new_curvature:.9f}")
            modified += 1
        return {"arc_records_modified": modified, "arc_curvature_clamped": clamped}

    def _perturb_object_density(self, root: ET.Element, scale: float) -> Dict[str, Any]:
        """Keep a seeded round(n * scale) subset of map objects."""
        # Stdlib ElementTree has no getparent(); collect parent->object pairs by walk.
        pairs: List[Any] = []
        for parent in root.iter():
            for obj in parent.findall("object"):
                pairs.append((parent, obj))
        if not pairs:
            return {"objects_before": 0, "objects_after": 0}
        keep_count = int(round(len(pairs) * scale))
        keep_count = max(0, min(len(pairs), keep_count))
        keep_ids = set(self.rng.sample(range(len(pairs)), keep_count))
        removed = 0
        for idx in range(len(pairs) - 1, -1, -1):
            if idx not in keep_ids:
                pairs[idx][0].remove(pairs[idx][1])
                removed += 1
        return {
            "objects_before": len(pairs),
            "objects_after": len(pairs) - removed,
        }

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    def apply_to_map(
        self,
        xodr_path: str,
        action: Dict[str, Any],
        out_dir: Optional[str] = None,
    ) -> str:
        """
        Apply a perturbation action to an OpenDRIVE map.

        Parameters
        ----------
        xodr_path : str
            Path to input XODR file.
        action : Dict[str, Any]
            Perturbation parameters (lane_width_scale, curvature_noise,
            object_density_scale). Bounds are enforced by ``validate_action``.
        out_dir : Optional[str]
            Directory for the perturbed copy. Defaults to
            ``<input_dir>/fuzz_out``.

        Returns
        -------
        str
            Path to the perturbed XODR file.
        """
        action = self.validate_action(action)
        src = Path(xodr_path)
        if not src.is_file():
            raise FileNotFoundError(f"input xodr not found: {src}")
        tree = ET.parse(src)
        root = tree.getroot()

        width_stats = self._perturb_lane_widths(root, float(action["lane_width_scale"]))
        curvature_stats = self._perturb_curvature(root, float(action["curvature_noise"]))
        object_stats = self._perturb_object_density(root, float(action["object_density_scale"]))

        out_root = Path(out_dir) if out_dir else src.parent / "fuzz_out"
        out_root.mkdir(parents=True, exist_ok=True)
        out_path = out_root / f"{src.stem}_fuzz_seed{self.seed}_ep{self._episode_count}.xodr"
        tree.write(out_path, encoding="utf-8", xml_declaration=True)
        self._episode_count += 1

        input_sha256 = hashlib.sha256(src.read_bytes()).hexdigest()
        output_sha256 = hashlib.sha256(out_path.read_bytes()).hexdigest()
        report = {
            "seed": self.seed,
            "episode": self._episode_count - 1,
            "action": action,
            "input": str(src.resolve()),
            "input_sha256": input_sha256,
            "output": str(out_path.resolve()),
            "output_sha256": output_sha256,
            "width": width_stats,
            "curvature": curvature_stats,
            "objects": object_stats,
        }
        (out_root / f"{out_path.name}.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        return str(out_path)

    # ------------------------------------------------------------------
    # Episode logic
    # ------------------------------------------------------------------
    def run_episode(self, xodr_path: str, out_dir: Optional[str] = None) -> str:
        """
        Run a single fuzzing episode.

        Returns
        -------
        str
            Path to the resulting map.
        """
        action = self.sample_action()
        return self.apply_to_map(xodr_path, action, out_dir=out_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description="Perturb an OpenDRIVE map with a seeded RL-fuzzer action")
    ap.add_argument("--xodr", required=True, help="input XODR file")
    ap.add_argument("--seed", type=int, default=0, help="RNG seed")
    ap.add_argument("--episodes", type=int, default=1, help="number of episodes")
    ap.add_argument("--out-dir", default=None, help="output directory (default <input_dir>/fuzz_out)")
    ap.add_argument("--lane-width-scale", type=float, default=None)
    ap.add_argument("--curvature-noise", type=float, default=None)
    ap.add_argument("--object-density-scale", type=float, default=None)
    args = ap.parse_args()

    fuzzer = RLFuzzer(seed=args.seed)
    fixed = {
        "lane_width_scale": args.lane_width_scale,
        "curvature_noise": args.curvature_noise,
        "object_density_scale": args.object_density_scale,
    }
    for _ in range(args.episodes):
        if all(v is None for v in fixed.values()):
            action = fuzzer.sample_action()
        else:
            sampled = fuzzer.sample_action()
            action = {k: (fixed[k] if fixed[k] is not None else sampled[k]) for k in fixed}
        out = fuzzer.apply_to_map(args.xodr, action, out_dir=args.out_dir)
        print(json.dumps({"episode": fuzzer._episode_count - 1, "action": action, "output": out}))
    return 0


if __name__ == "__main__":
    sys.exit(main())