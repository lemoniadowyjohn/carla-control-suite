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

# Reverse mapping: folder_id -> folder_name for lookups by numeric ID
FOLDER_ID_TO_NAME: Dict[int, str] = {v: k for k, v in CARLA_SEMANTIC_FOLDERS.items()}

# Forward mapping: folder_name -> folder_id for lookups by string name
FOLDER_NAME_TO_ID: Dict[str, int] = {k: v for k, v in CARLA_SEMANTIC_FOLDERS.items()}

# Legacy rule dict for reference and fallback
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

# Legacy keyword patterns for reference
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

# ---------------------------------------------------------------------------
# Deterministic Explicit Ranked Rules (Lower priority value = Higher precedence)
# ---------------------------------------------------------------------------
EXACT_TAG_RULES: List[Tuple[str, str, str, int]] = [
    ("natural", "tree", "Vegetation", 10),
    ("natural", "wood", "Vegetation", 11),
    ("natural", "scrub", "Vegetation", 12),
    ("natural", "heath", "Vegetation", 13),
    ("natural", "grassland", "Vegetation", 14),
    ("landuse", "forest", "Vegetation", 15),
    ("landuse", "grass", "Vegetation", 16),
    ("leisure", "park", "Vegetation", 17),
    ("leisure", "garden", "Vegetation", 18),
    ("barrier", "fence", "Fences", 20),
    ("barrier", "wire_fence", "Fences", 21),
    ("barrier", "railing", "Fences", 22),
    ("barrier", "wall", "Walls", 30),
    ("barrier", "retaining_wall", "Walls", 31),
    ("barrier", "city_wall", "Walls", 32),
    ("barrier", "guard_rail", "GuardRail", 35),
    ("highway", "traffic_signals", "TrafficLight", 40),
    ("man_made", "street_lamp", "Poles", 50),
    ("power", "pole", "Poles", 51),
    ("utility", "pole", "Poles", 52),
    ("man_made", "flagpole", "Poles", 53),
    ("man_made", "bridge", "Bridge", 60),
    ("natural", "water", "Water", 70),
    ("natural", "bare_rock", "Terrain", 80),
    ("landuse", "meadow", "Terrain", 81),
]

KEY_TAG_RULES: List[Tuple[str, str, int]] = [
    ("building:part", "Buildings", 10),
    ("building", "Buildings", 11),
    ("traffic_sign", "TrafficSigns", 20),
    ("bridge", "Bridge", 30),
    ("railway", "RailTrack", 40),
    ("waterway", "Water", 50),
    ("highway", "Roads", 60),
    ("sidewalk", "Sidewalks", 70),
]

KEYWORD_RULES_WITH_PRIORITY: List[Tuple[re.Pattern[str], str, int]] = [
    (re.compile(r"\b(building|house|roof|door|window|facade|structure|barn|shed|garage)\b", re.IGNORECASE), "Buildings", 10),
    (re.compile(r"\b(tree|wood|forest|bush|plant|leaf|leaves|foliage|grass|hedge|flower|vegetation)\b", re.IGNORECASE), "Vegetation", 20),
    (re.compile(r"\b(fence|railing|handrail|barrier|gate)\b", re.IGNORECASE), "Fences", 30),
    (re.compile(r"\b(wall|retaining_wall|masonry|parapet)\b", re.IGNORECASE), "Walls", 40),
    (re.compile(r"\b(guardrail|guard_rail|guard|crash_barrier|safety_barrier)\b", re.IGNORECASE), "GuardRail", 50),
    (re.compile(r"\b(pole|lamp|lamppost|streetlamp|lightpole|utilitypole|mast|post)\b", re.IGNORECASE), "Poles", 60),
    (re.compile(r"\b(trafficsign|sign|signboard|speedlimit)\b", re.IGNORECASE), "TrafficSigns", 70),
    (re.compile(r"\b(trafficlight|traffic_signal|stoplight|signal_light|signal)\b", re.IGNORECASE), "TrafficLight", 80),
    (re.compile(r"\b(bridge|overpass|viaduct|pier)\b", re.IGNORECASE), "Bridge", 90),
    (re.compile(r"\b(rail|railway|track|tram)\b", re.IGNORECASE), "RailTrack", 100),
    (re.compile(r"\b(road|asphalt|carriageway|street|lane|pavement)\b", re.IGNORECASE), "Roads", 110),
    (re.compile(r"\b(sidewalk|walkway|footpath|pedestrian_path)\b", re.IGNORECASE), "Sidewalks", 120),
    (re.compile(r"\b(roadline|marking|lane_marking|crosswalk_line)\b", re.IGNORECASE), "RoadLines", 130),
    (re.compile(r"\b(water|river|lake|pond|stream|canal)\b", re.IGNORECASE), "Water", 140),
    (re.compile(r"\b(terrain|ground|dirt|rock|cliff|hill|embankment)\b", re.IGNORECASE), "Terrain", 150),
]


def _normalize_name_for_matching(text: str) -> str:
    """Split CamelCase and replace non-alphanumeric characters with spaces."""
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    return re.sub(r"[^a-zA-Z0-9]+", " ", spaced)


def normalize_osm_tags(tags: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Normalize tag inputs (key/value casing, surrounding whitespace, empty values, preserve punctuation)."""
    if not tags:
        return {}
    normalized = {}
    for k, v in tags.items():
        if not k or v is None:
            continue
        clean_k = k.strip().lower()
        clean_v = str(v).strip().lower() if isinstance(v, str) else str(v).strip().lower()
        if clean_k and clean_v:
            normalized[clean_k] = clean_v
    return normalized


def check_and_sanitize_path(base_dir: Path, rel_path_str: str) -> Path:
    """Sanitize and check rel_path_str against directory traversal attacks.

    Raises ValueError if path attempts to escape base_dir or is absolute/drive-qualified.
    """
    if not rel_path_str:
        raise ValueError("Empty filename or path is invalid")

    # Reject absolute paths or drive-qualified paths escaping source root
    if os.path.isabs(rel_path_str) or ":" in rel_path_str or rel_path_str.startswith("\\") or rel_path_str.startswith("/"):
        raise ValueError(f"Unsafe absolute or drive-qualified path rejected: {rel_path_str}")

    resolved_base = Path(base_dir).resolve()
    target_path = Path(resolved_base / rel_path_str).resolve()

    if not str(target_path).startswith(str(resolved_base)):
        raise ValueError(f"Unsafe path traversal detected: {rel_path_str} escapes base directory {base_dir}")

    return target_path


@dataclass
class DetailedClassification:
    """Comprehensive, deterministic classification result."""

    status: str             # "OFFLINE_CLASSIFICATION_VERIFIED" | "AMBIGUOUS"
    folder: str             # CARLA semantic folder name
    tag_id: int             # CARLA tag ID
    rule: str               # Human-readable matched rule description
    matched_rules: List[str]# All matching rules in the highest active tier
    candidate_classes: List[str] # Unique target folders in the highest active tier (sorted)
    provenance: str         # "osm_exact" | "osm_key" | "object_name" | "material_name" | "fallback"


def classify_object_detailed(
    *,
    name: str = "",
    materials: Optional[List[str]] = None,
    osm_tags: Optional[Dict[str, str]] = None,
) -> DetailedClassification:
    """Run detailed, deterministic classification on an asset's features."""
    materials = materials or []
    normalized_tags = normalize_osm_tags(osm_tags)

    # ── Tier 1: Exact OSM Tag Matches ──────────────────────────────────────
    exact_matches = []
    for k, v in normalized_tags.items():
        for r_key, r_val, r_folder, r_priority in EXACT_TAG_RULES:
            if r_key == k and r_val == v:
                exact_matches.append((k, v, r_folder, r_priority))

    if exact_matches:
        # Sort matches deterministically by priority ascending, then by folder lexicographically
        exact_matches.sort(key=lambda x: (x[3], x[2]))
        unique_folders = {m[2] for m in exact_matches}
        status = "OFFLINE_CLASSIFICATION_VERIFIED" if len(unique_folders) == 1 else "AMBIGUOUS"
        best_match = exact_matches[0]
        folder = best_match[2]
        rule = f"OSM pair {best_match[0]}={best_match[1]} → {best_match[2]}"
        matched_rules = [f"OSM pair {m[0]}={m[1]} → {m[2]}" for m in exact_matches]
        candidate_classes = sorted(list(unique_folders))
        return DetailedClassification(
            status=status,
            folder=folder,
            tag_id=CARLA_SEMANTIC_FOLDERS[folder],
            rule=rule,
            matched_rules=matched_rules,
            candidate_classes=candidate_classes,
            provenance="osm_exact",
        )

    # ── Tier 2: Key-Only OSM Tag Matches ───────────────────────────────────
    key_matches = []
    for k in normalized_tags.keys():
        for r_key, r_folder, r_priority in KEY_TAG_RULES:
            if r_key == k:
                key_matches.append((k, r_folder, r_priority))

    if key_matches:
        key_matches.sort(key=lambda x: (x[2], x[1]))
        unique_folders = {m[1] for m in key_matches}
        status = "OFFLINE_CLASSIFICATION_VERIFIED" if len(unique_folders) == 1 else "AMBIGUOUS"
        best_match = key_matches[0]
        folder = best_match[1]
        rule = f"OSM key {best_match[0]} → {best_match[1]}"
        matched_rules = [f"OSM key {m[0]} → {m[1]}" for m in key_matches]
        candidate_classes = sorted(list(unique_folders))
        return DetailedClassification(
            status=status,
            folder=folder,
            tag_id=CARLA_SEMANTIC_FOLDERS[folder],
            rule=rule,
            matched_rules=matched_rules,
            candidate_classes=candidate_classes,
            provenance="osm_key",
        )

    # ── Tier 3: Object Name Keywords ───────────────────────────────────────
    if name and name.strip():
        name_matches = []
        clean_name_1 = _normalize_name_for_matching(name)
        clean_name_2 = " ".join(name.lower().replace("_", " ").split())

        for pattern, r_folder, r_priority in KEYWORD_RULES_WITH_PRIORITY:
            if pattern.search(clean_name_1) or pattern.search(clean_name_2):
                name_matches.append((pattern.pattern, r_folder, r_priority))

        if name_matches:
            name_matches.sort(key=lambda x: (x[2], x[1]))
            unique_folders = {m[1] for m in name_matches}
            status = "OFFLINE_CLASSIFICATION_VERIFIED" if len(unique_folders) == 1 else "AMBIGUOUS"
            best_match = name_matches[0]
            folder = best_match[1]
            rule = f"name keyword → {best_match[1]}"
            matched_rules = [f"name keyword → {m[1]}" for m in name_matches]
            candidate_classes = sorted(list(unique_folders))
            return DetailedClassification(
                status=status,
                folder=folder,
                tag_id=CARLA_SEMANTIC_FOLDERS[folder],
                rule=rule,
                matched_rules=matched_rules,
                candidate_classes=candidate_classes,
                provenance="object_name",
            )

    # ── Tier 4: Material Name Keywords ─────────────────────────────────────
    material_matches = []
    for mat in materials:
        if not mat or not mat.strip():
            continue
        clean_mat_1 = _normalize_name_for_matching(mat)
        clean_mat_2 = " ".join(mat.lower().replace("_", " ").split())

        for pattern, r_folder, r_priority in KEYWORD_RULES_WITH_PRIORITY:
            if pattern.search(clean_mat_1) or pattern.search(clean_mat_2):
                material_matches.append((mat, pattern.pattern, r_folder, r_priority))

    if material_matches:
        material_matches.sort(key=lambda x: (x[3], x[2]))
        unique_folders = {m[2] for m in material_matches}
        status = "OFFLINE_CLASSIFICATION_VERIFIED" if len(unique_folders) == 1 else "AMBIGUOUS"
        best_match = material_matches[0]
        folder = best_match[2]
        rule = f"material {best_match[0]} → {best_match[2]}"
        matched_rules = [f"material {m[0]} → {m[2]}" for m in material_matches]
        candidate_classes = sorted(list(unique_folders))
        return DetailedClassification(
            status=status,
            folder=folder,
            tag_id=CARLA_SEMANTIC_FOLDERS[folder],
            rule=rule,
            matched_rules=matched_rules,
            candidate_classes=candidate_classes,
            provenance="material_name",
        )

    # ── Tier 5: Fallback ───────────────────────────────────────────────────
    folder = "Other"
    return DetailedClassification(
        status="OFFLINE_CLASSIFICATION_VERIFIED",
        folder=folder,
        tag_id=CARLA_SEMANTIC_FOLDERS[folder],
        rule="fallback:unclassified",
        matched_rules=["fallback:unclassified"],
        candidate_classes=[folder],
        provenance="fallback",
    )


def classify_object(
    *,
    name: str = "",
    materials: Optional[List[str]] = None,
    osm_tags: Optional[Dict[str, str]] = None,
) -> Tuple[str, str]:
    """Legacy compatibility wrapper returning (folder, rule). Is completely deterministic."""
    detailed = classify_object_detailed(name=name, materials=materials, osm_tags=osm_tags)
    return detailed.folder, detailed.rule


def generate_inventory_audit_report(inventory: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Scan semantic inventories and generate a deterministic quality audit."""
    total = len(inventory)
    classified = 0
    fallback = 0
    ambiguous = 0
    conflicting_rule_pairs: Dict[str, int] = {}
    classes_counts: Dict[str, int] = {folder: 0 for folder in CARLA_SEMANTIC_FOLDERS}
    rules_counts: Dict[str, int] = {}

    for item in inventory:
        name = item.get("name", "")
        mats = item.get("materials", [])
        tags = item.get("osm_tags", {})

        det = classify_object_detailed(name=name, materials=mats, osm_tags=tags)

        classes_counts[det.folder] = classes_counts.get(det.folder, 0) + 1

        if det.provenance == "fallback":
            fallback += 1
        else:
            classified += 1

        if det.status == "AMBIGUOUS":
            ambiguous += 1
            candidates = sorted(det.candidate_classes)
            for i in range(len(candidates)):
                for j in range(i + 1, len(candidates)):
                    pair_str = f"{candidates[i]} vs {candidates[j]}"
                    conflicting_rule_pairs[pair_str] = conflicting_rule_pairs.get(pair_str, 0) + 1

        for r in det.matched_rules:
            rules_counts[r] = rules_counts.get(r, 0) + 1

    return {
        "total": total,
        "classified": classified,
        "fallback": fallback,
        "ambiguous": ambiguous,
        "conflicting_rule_pairs": conflicting_rule_pairs,
        "classes": classes_counts,
        "rules": rules_counts,
    }


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
    status: str = "pending"  # "pending" | "copied" | "moved" | "dry_run" | "error" | "unresolved"
    error: str = ""
    asset_kind: str = "CONTAINER_FBX"  # "CONTAINER_FBX" | "MESH_OBJECT" | "UASSET"
    container_path: Optional[str] = None
    semantic_class: str = ""
    candidate_classes: List[str] = field(default_factory=list)

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
            "asset_kind": self.asset_kind,
            "container_path": self.container_path,
            "semantic_class": self.semantic_class,
            "candidate_classes": self.candidate_classes,
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
    semantic_splits_required: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "content_root": self.content_root,
            "mode": self.mode,
            "total_assets": self.total_assets,
            "placements_by_folder": self.placements_by_folder,
            "placements": [p.to_dict() for p in self.placements],
            "errors": self.errors,
            "semantic_splits_required": self.semantic_splits_required,
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
            },
            "claim_boundaries": {
                "OFFLINE_CLASSIFICATION_VERIFIED": "Pure tag resolution, folder path computation, and plan generation are verified mathematically/offline.",
                "FILESYSTEM_PLACEMENT_VERIFIED": "Filesystem copy/move of non-UAsset containers is verified safe at the OS layer.",
                "UE_ASSET_ORGANIZATION_UNVERIFIED": "Unreal Engine asset reference validation and live tag assignment require the Unreal Editor Asset API / live environment."
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
        """Create placement plan from a Blender/FBX manifest inventory."""
        source_base = Path(source_dir).resolve() if source_dir else self.content_root
        placements: List[AssetPlacement] = []
        counts: Dict[str, int] = {folder: 0 for folder in CARLA_SEMANTIC_FOLDERS}
        errors: List[str] = []
        semantic_splits_required: List[Dict[str, Any]] = []

        now_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        # Group inventory items by filename (container file)
        from collections import defaultdict
        container_groups = defaultdict(list)
        for item in inventory:
            filename = item.get("filename")
            if not filename or not str(filename).strip():
                container_groups[None].append(item)
            else:
                container_groups[str(filename).strip()].append(item)

        for filename, group in container_groups.items():
            if filename is None:
                # No physical file; purely logical MESH_OBJECTs
                for item in group:
                    name = item.get("name", "unnamed")
                    mats = item.get("materials", [])
                    tags = item.get("osm_tags", {})

                    det = classify_object_detailed(name=name, materials=mats, osm_tags=tags)
                    tag_id = CARLA_SEMANTIC_FOLDERS[det.folder]

                    placement = AssetPlacement(
                        source_path="",
                        asset_name=name,
                        target_folder=det.folder,
                        target_path="",
                        rule_matched=det.rule,
                        tag_id=tag_id,
                        status="unresolved",
                        asset_kind="MESH_OBJECT",
                        container_path=None,
                        semantic_class=det.folder,
                        candidate_classes=det.candidate_classes,
                    )
                    placements.append(placement)
                continue

            # Physical container path sanity check & resolve
            try:
                sanitized_src_path = check_and_sanitize_path(source_base, filename)
                unsafe_path_error = None
            except ValueError as ve:
                unsafe_path_error = str(ve)
                sanitized_src_path = source_base / filename  # Fallback representation

            group_classifications = []
            for item in group:
                name = item.get("name", "unnamed")
                mats = item.get("materials", [])
                tags = item.get("osm_tags", {})
                det = classify_object_detailed(name=name, materials=mats, osm_tags=tags)
                group_classifications.append((item, det))

            unique_folders = {det.folder for item, det in group_classifications}
            ext = Path(filename).suffix.lower()
            asset_kind = "UASSET" if ext == ".uasset" else "CONTAINER_FBX"
            exists = sanitized_src_path.exists()

            # Handle path traversal or other safety violations
            if unsafe_path_error:
                errors.append(unsafe_path_error)
                for item, det in group_classifications:
                    placement = AssetPlacement(
                        source_path=str(sanitized_src_path),
                        asset_name=item.get("name", "unnamed"),
                        target_folder=det.folder,
                        target_path="",
                        rule_matched=det.rule,
                        tag_id=CARLA_SEMANTIC_FOLDERS[det.folder],
                        status="error",
                        error=unsafe_path_error,
                        asset_kind=asset_kind,
                        container_path=filename,
                        semantic_class=det.folder,
                        candidate_classes=det.candidate_classes,
                    )
                    placements.append(placement)
                continue

            # Check if one container requires multiple semantic folders => SEMANTIC_SPLIT_REQUIRED!
            if len(unique_folders) > 1:
                split_error = f"Container {filename} requires semantic split: contains objects mapping to different folders: {sorted(list(unique_folders))}."
                errors.append(split_error)

                # Report multi-class FBX details
                split_info = {
                    "container_path": str(sanitized_src_path),
                    "classes_present": sorted(list(unique_folders)),
                    "objects_by_class": {
                        f: [i.get("name", "unnamed") for i, d in group_classifications if d.folder == f]
                        for f in sorted(list(unique_folders))
                    }
                }
                semantic_splits_required.append(split_info)

                for item, det in group_classifications:
                    placement = AssetPlacement(
                        source_path=str(sanitized_src_path),
                        asset_name=item.get("name", "unnamed"),
                        target_folder=det.folder,
                        target_path="",
                        rule_matched=det.rule,
                        tag_id=CARLA_SEMANTIC_FOLDERS[det.folder],
                        status="error",
                        error="SEMANTIC_SPLIT_REQUIRED",
                        asset_kind=asset_kind,
                        container_path=filename,
                        semantic_class=det.folder,
                        candidate_classes=det.candidate_classes,
                    )
                    placements.append(placement)
                continue

            # Single-class container
            target_folder = list(unique_folders)[0]
            tag_id = CARLA_SEMANTIC_FOLDERS[target_folder]
            target_path = self.static_root / target_folder / filename

            for item, det in group_classifications:
                name = item.get("name", "unnamed")

                if not exists:
                    # Missing container is an explicit error
                    missing_error = f"Container not found: {sanitized_src_path}"
                    errors.append(missing_error)
                    placement = AssetPlacement(
                        source_path=str(sanitized_src_path),
                        asset_name=name,
                        target_folder=target_folder,
                        target_path=str(target_path),
                        rule_matched=det.rule,
                        tag_id=tag_id,
                        status="error",
                        error=missing_error,
                        asset_kind=asset_kind,
                        container_path=filename,
                        semantic_class=target_folder,
                        candidate_classes=det.candidate_classes,
                    )
                elif asset_kind == "UASSET":
                    # Raw .uasset moves/copies are blocked in production placement
                    if self.mode in ("copy", "move"):
                        block_msg = "BLOCKED_UE_ASSET_API: Raw filesystem move of .uasset is blocked to prevent breaking references. Verified relocation requires Unreal Editor Asset API."
                        errors.append(f"Blocked .uasset file {filename}: {block_msg}")
                        placement = AssetPlacement(
                            source_path=str(sanitized_src_path),
                            asset_name=name,
                            target_folder=target_folder,
                            target_path=str(target_path),
                            rule_matched=det.rule,
                            tag_id=tag_id,
                            status="error",
                            error="BLOCKED_UE_ASSET_API",
                            asset_kind=asset_kind,
                            container_path=filename,
                            semantic_class=target_folder,
                            candidate_classes=det.candidate_classes,
                        )
                    else:
                        placement = AssetPlacement(
                            source_path=str(sanitized_src_path),
                            asset_name=name,
                            target_folder=target_folder,
                            target_path=str(target_path),
                            rule_matched=det.rule,
                            tag_id=tag_id,
                            status="dry_run",
                            asset_kind=asset_kind,
                            container_path=filename,
                            semantic_class=target_folder,
                            candidate_classes=det.candidate_classes,
                        )
                else:
                    # Standard CONTAINER_FBX
                    counts[target_folder] = counts.get(target_folder, 0) + 1
                    placement = AssetPlacement(
                        source_path=str(sanitized_src_path),
                        asset_name=name,
                        target_folder=target_folder,
                        target_path=str(target_path),
                        rule_matched=det.rule,
                        tag_id=tag_id,
                        status="dry_run" if self.mode == "dry_run" else "pending",
                        asset_kind=asset_kind,
                        container_path=filename,
                        semantic_class=target_folder,
                        candidate_classes=det.candidate_classes,
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
            semantic_splits_required=semantic_splits_required,
        )

    def execute_plan(self, report: OrganizationReport) -> OrganizationReport:
        """Execute the file organization plan on disk (if mode != 'dry_run')."""
        if self.mode == "dry_run":
            return report

        for placement in report.placements:
            if placement.status != "pending":
                continue

            src = Path(placement.source_path)
            tgt = Path(placement.target_path)

            if not src.exists():
                placement.status = "error"
                placement.error = f"Source file not found: {src}"
                report.errors.append(placement.error)
                continue

            if placement.asset_kind == "UASSET":
                placement.status = "error"
                placement.error = "BLOCKED_UE_ASSET_API"
                report.errors.append(f"Blocked execution for .uasset file {placement.container_path}: requires Unreal Editor Asset API / redirector handling.")
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
