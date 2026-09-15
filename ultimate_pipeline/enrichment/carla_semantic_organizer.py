#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CARLA Post-Ingestion Semantic Tag Organizer.

This module automates the placement of imported visual content (FBX / static meshes)
into CARLA's documented Unreal Engine folder structure (`Content/Carla/Static/<TagFolder>/`).

CARLA Semantic Tagging Mechanism
--------------------------------
CARLA tags static meshes by inspecting their parent content folder under `Carla/Static/`
in Unreal Engine (`Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Game/Tagger.cpp`, function
`GetLabelByFolderName`).

The standard CARLA 0.9.14+ folder-to-semantic-tag mapping is:
    - Buildings      -> Tag 1  (Buildings)
    - Fences         -> Tag 2  (Fences)
    - Other          -> Tag 3  (Other)
    - Pedestrians    -> Tag 4  (Pedestrians)
    - Poles          -> Tag 5  (Poles)
    - RoadLines      -> Tag 6  (RoadLines)
    - Roads          -> Tag 7  (Roads)
    - Sidewalks      -> Tag 8  (Sidewalks)
    - Vegetation     -> Tag 9  (Vegetation)
    - Vehicles       -> Tag 10 (Vehicles)
    - Walls          -> Tag 11 (Walls)
    - TrafficSigns   -> Tag 12 (TrafficSigns)
    - Sky            -> Tag 13 (Sky)
    - Ground         -> Tag 14 (Ground)
    - Bridge         -> Tag 15 (Bridge)
    - RailTrack      -> Tag 16 (RailTrack)
    - GuardRail      -> Tag 17 (GuardRail)
    - TrafficLight   -> Tag 18 (TrafficLight)
    - Static         -> Tag 19 (Static)
    - Dynamic        -> Tag 20 (Dynamic)
    - Water          -> Tag 21 (Water)
    - Terrain        -> Tag 22 (Terrain)

Classification Strategy
-----------------------
This module classifies objects using a multi-tiered rule engine:
    1. Explicit OSM tags / metadata (e.g. ``building=*``, ``natural=tree``, ``barrier=fence``)
    2. Object / mesh name prefix heuristics (e.g. ``Building_01``, ``Tree_45``, ``Pole_12``)
    3. Material name heuristics (e.g. ``Building_Facade_Mat``, ``Tree_Leaves_Mat``)
    4. Default fallback: ``Other``

Claim & Verification Boundary
-----------------------------
    - CONFIRMED (Offline Testable): Pure tag resolution, folder path computation,
      plan generation, and file operations on mock/synthetic content trees.
    - UNVERIFIED (Requires Live UE4 Editor):
      1. Whether raw filesystem moves of ``.uasset`` files post-import break UE4 internal
         asset references (redirectors) vs requiring Unreal Python API (`EditorAssetLibrary`).
      2. Whether `make import` places FBX meshes directly into `Carla/Static/` or into
         `Content/<MapName>/`.
      3. Precise runtime tag assignment by `Tagger.cpp` for nested subdirectories under
         `Carla/Static/<TagFolder>/<Subdir>/`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# CARLA Semantic Tag Folders & IDs (matching Tagger.cpp / CityObjectLabel)
# ---------------------------------------------------------------------------
CARLA_SEMANTIC_FOLDERS: Dict[str, int] = {
    "Buildings": 1,
    "Fences": 2,
    "Other": 3,
    "Pedestrians": 4,
    "Poles": 5,
    "RoadLines": 6,
    "Roads": 7,
    "Sidewalks": 8,
    "Vegetation": 9,
    "Vehicles": 10,
    "Walls": 11,
    "TrafficSigns": 12,
    "Sky": 13,
    "Ground": 14,
    "Bridge": 15,
    "RailTrack": 16,
    "GuardRail": 17,
    "TrafficLight": 18,
    "Static": 19,
    "Dynamic": 20,
    "Water": 21,
    "Terrain": 22,
}

# ---------------------------------------------------------------------------
# Classification Rules Engine
# ---------------------------------------------------------------------------
# Priority 1: OSM Tag -> CARLA Semantic Tag Folder
OSM_TAG_TO_FOLDER: Dict[str, str] = {
    "building": "Buildings",
    "building:part": "Buildings",
    "natural=tree": "Vegetation",
    "natural=wood": "Vegetation",
    "natural=scrub": "Vegetation",
    "natural=heath": "Vegetation",
    "natural=grassland": "Vegetation",
    "landuse=forest": "Vegetation",
    "landuse=grass": "Vegetation",
    "leisure=park": "Vegetation",
    "leisure=garden": "Vegetation",
    "barrier=fence": "Fences",
    "barrier=wire_fence": "Fences",
    "barrier=railing": "Fences",
    "barrier=wall": "Walls",
    "barrier=retaining_wall": "Walls",
    "barrier=city_wall": "Walls",
    "barrier=guard_rail": "GuardRail",
    "highway=traffic_signals": "TrafficLight",
    "traffic_sign": "TrafficSigns",
    "man_made=street_lamp": "Poles",
    "power=pole": "Poles",
    "utility=pole": "Poles",
    "man_made=flagpole": "Poles",
    "man_made=bridge": "Bridge",
    "bridge": "Bridge",
    "railway": "RailTrack",
    "natural=water": "Water",
    "waterway": "Water",
    "natural=bare_rock": "Terrain",
    "landuse=meadow": "Terrain",
    "highway": "Roads",
    "sidewalk": "Sidewalks",
}

# Priority 2: Keyword pattern -> CARLA Semantic Tag Folder
KEYWORD_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(building|house|roof|door|window|facade|structure|barn|shed|garage)\b", re.IGNORECASE), "Buildings"),
    (re.compile(r"\b(tree|wood|forest|bush|plant|leaf|leaves|foliage|grass|hedge|flower|vegetation)\b", re.IGNORECASE), "Vegetation"),
    (re.compile(r"\b(fence|railing|handrail|barrier|gate)\b", re.IGNORECASE), "Fences"),
    (re.compile(r"\b(wall|retaining_wall|masonry|parapet)\b", re.IGNORECASE), "Walls"),
    (re.compile(r"\b(guardrail|guard_rail|guard|crash_barrier|safety_barrier)\b", re.IGNORECASE), "GuardRail"),
    (re.compile(r"\b(pole|lamp|lamppost|streetlamp|lightpole|utilitypole|mast|post)\b", re.IGNORECASE), "Poles"),
    (re.compile(r"\b(trafficsign|sign|signboard|speedlimit)\b", re.IGNORECASE), "TrafficSigns"),
    (re.compile(r"\b(trafficlight|traffic_signal|stoplight|signal_light|signal)\b", re.IGNORECASE), "TrafficLight"),
    (re.compile(r"\b(bridge|overpass|viaduct|pier)\b", re.IGNORECASE), "Bridge"),
    (re.compile(r"\b(rail|railway|track|tram)\b", re.IGNORECASE), "RailTrack"),
    (re.compile(r"\b(road|asphalt|carriageway|street|lane|pavement)\b", re.IGNORECASE), "Roads"),
    (re.compile(r"\b(sidewalk|walkway|footpath|pedestrian_path)\b", re.IGNORECASE), "Sidewalks"),
    (re.compile(r"\b(roadline|marking|lane_marking|crosswalk_line)\b", re.IGNORECASE), "RoadLines"),
    (re.compile(r"\b(water|river|lake|pond|stream|canal)\b", re.IGNORECASE), "Water"),
    (re.compile(r"\b(terrain|ground|dirt|rock|cliff|hill|embankment)\b", re.IGNORECASE), "Terrain"),
]


def _normalize_name_for_matching(text: str) -> str:
    """Split CamelCase and replace non-alphanumeric characters with spaces."""
    # Split CamelCase: "OakTree" -> "Oak Tree"
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    return re.sub(r"[^a-zA-Z0-9]+", " ", spaced)


def classify_object(
    *,
    name: str = "",
    materials: Optional[List[str]] = None,
    osm_tags: Optional[Dict[str, str]] = None,
) -> Tuple[str, str]:
    """Determine the CARLA semantic tag folder for an asset.

    Returns:
        (folder_name, rule_matched) where folder_name is one of CARLA_SEMANTIC_FOLDERS keys.
    """
    materials = materials or []
    osm_tags = osm_tags or {}

    # 1. Check explicit OSM tags
    for k, v in osm_tags.items():
        if not v:
            continue
        # Exact pair match e.g. "barrier=fence"
        pair_key = f"{k}={v}"
        if pair_key in OSM_TAG_TO_FOLDER:
            return (OSM_TAG_TO_FOLDER[pair_key], f"osm_tag:{pair_key}")
        # Key-only match e.g. "building"
        if k in OSM_TAG_TO_FOLDER:
            return (OSM_TAG_TO_FOLDER[k], f"osm_tag_key:{k}")

    # 2. Check object/mesh name keywords
    if name:
        clean_name = _normalize_name_for_matching(name)
        for pattern, folder in KEYWORD_RULES:
            if pattern.search(clean_name):
                return (folder, f"object_name:{pattern.pattern}")

    # 3. Check material name keywords
    for mat in materials:
        if not mat:
            continue
        clean_mat = _normalize_name_for_matching(mat)
        for pattern, folder in KEYWORD_RULES:
            if pattern.search(clean_mat):
                return (folder, f"material_name:{mat}")

    # 4. Fallback
    return ("Other", "fallback:unclassified")


# ---------------------------------------------------------------------------
# Organization Execution & Manifest Generation
# ---------------------------------------------------------------------------
@dataclass
class AssetPlacement:
    """Placement decision for a single imported asset or mesh."""

    source_path: str
    asset_name: str
    target_folder: str
    target_path: str
    rule_matched: str
    tag_id: int
    status: str = "pending"  # "pending" | "copied" | "moved" | "dry_run" | "error"
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "asset_name": self.asset_name,
            "target_folder": self.target_folder,
            "target_path": self.target_path,
            "rule_matched": self.rule_matched,
            "tag_id": self.tag_id,
            "status": self.status,
            "error": self.error,
        }


@dataclass
class OrganizationReport:
    """Summary report of a semantic tagging organization run."""

    timestamp: str
    content_root: str
    mode: str  # "dry_run" | "copy" | "move"
    total_assets: int
    placements_by_folder: Dict[str, int]
    placements: List[AssetPlacement]
    errors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "content_root": self.content_root,
            "mode": self.mode,
            "total_assets": self.total_assets,
            "placements_by_folder": self.placements_by_folder,
            "placements": [p.to_dict() for p in self.placements],
            "errors": self.errors,
            "verification_notes": {
                "confirmed": [
                    "CARLA Tagger.cpp parses subfolders under Carla/Static/<TagFolder>/ to assign CityObjectLabel enum.",
                    "Tag classification logic matches OSM tags, object names, and material names deterministically."
                ],
                "unverified_pending_live_ue4": [
                    "Raw filesystem move of imported .uasset files may break UE4 internal asset references if not updated via Unreal Editor Python API.",
                    "make import default landing folder placement (Content/<MapName>/ vs Content/Carla/Static/).",
                    "Nested subfolder recursion depth inside Tagger.cpp."
                ]
            }
        }


class CarlaSemanticOrganizer:
    """Organizes imported assets into CARLA's `Carla/Static/<TagFolder>/` directory structure."""

    def __init__(
        self,
        content_root: Path,
        mode: str = "dry_run",  # "dry_run" | "copy" | "move"
        target_static_relpath: str = "Carla/Static",
    ) -> None:
        self.content_root = Path(content_root).resolve()
        self.mode = mode
        self.static_root = self.content_root / target_static_relpath

    def plan_from_inventory(
        self,
        inventory: List[Dict[str, Any]],
        source_dir: Optional[Path] = None,
    ) -> OrganizationReport:
        """Create placement plan from a Blender/FBX manifest inventory.

        inventory item format:
            {"name": "Building_6_8", "materials": ["Wall_Mat"], "osm_tags": {...}, "filename": "Building_6_8.fbx"}
        """
        source_base = Path(source_dir).resolve() if source_dir else self.content_root
        placements: List[AssetPlacement] = []
        counts: Dict[str, int] = {folder: 0 for folder in CARLA_SEMANTIC_FOLDERS}
        errors: List[str] = []

        now_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        for item in inventory:
            name = item.get("name", "unnamed")
            mats = item.get("materials", [])
            tags = item.get("osm_tags", {})
            rel_filename = item.get("filename", f"{name}.fbx")

            folder, rule = classify_object(name=name, materials=mats, osm_tags=tags)
            tag_id = CARLA_SEMANTIC_FOLDERS[folder]

            src_path = source_base / rel_filename
            tgt_path = self.static_root / folder / rel_filename

            counts[folder] = counts.get(folder, 0) + 1

            placement = AssetPlacement(
                source_path=str(src_path),
                asset_name=name,
                target_folder=folder,
                target_path=str(tgt_path),
                rule_matched=rule,
                tag_id=tag_id,
                status="dry_run" if self.mode == "dry_run" else "pending",
            )
            placements.append(placement)

        return OrganizationReport(
            timestamp=now_str,
            content_root=str(self.content_root),
            mode=self.mode,
            total_assets=len(placements),
            placements_by_folder=counts,
            placements=placements,
            errors=errors,
        )

    def execute_plan(self, report: OrganizationReport) -> OrganizationReport:
        """Execute the file organization plan on disk (if mode != 'dry_run')."""
        if self.mode == "dry_run":
            return report

        for placement in report.placements:
            src = Path(placement.source_path)
            tgt = Path(placement.target_path)

            if not src.exists():
                placement.status = "error"
                placement.error = f"Source file not found: {src}"
                report.errors.append(placement.error)
                continue

            try:
                tgt.parent.mkdir(parents=True, exist_ok=True)
                if self.mode == "copy":
                    shutil.copy2(src, tgt)
                    placement.status = "copied"
                elif self.mode == "move":
                    shutil.move(src, tgt)
                    placement.status = "moved"
            except Exception as ex:
                placement.status = "error"
                placement.error = str(ex)
                report.errors.append(f"Failed to process {src}: {ex}")

        return report


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Organize imported CARLA map assets into Carla/Static/<TagFolder>/ structure."
    )
    parser.add_argument("--content-root", required=True, help="Path to Unreal project Content folder")
    parser.add_argument("--inventory-manifest", help="JSON manifest containing list of imported assets")
    parser.add_argument("--mode", choices=["dry_run", "copy", "move"], default="dry_run")
    parser.add_argument("--out-report", help="Output JSON report path")
    args = parser.parse_args()

    content_root = Path(args.content_root)
    organizer = CarlaSemanticOrganizer(content_root=content_root, mode=args.mode)

    inventory: List[Dict[str, Any]] = []
    if args.inventory_manifest and Path(args.inventory_manifest).exists():
        with open(args.inventory_manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
            inventory = data.get("objects", data.get("assets", []))

    report = organizer.plan_from_inventory(inventory)
    if args.mode != "dry_run":
        report = organizer.execute_plan(report)

    output_json = json.dumps(report.to_dict(), indent=2)
    if args.out_report:
        Path(args.out_report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_report).write_text(output_json, encoding="utf-8")
        print(f"[semantic_organizer] Report written to {args.out_report}")
    else:
        print(output_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
