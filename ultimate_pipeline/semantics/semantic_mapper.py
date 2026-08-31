from __future__ import annotations

import argparse
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# A deliberately SMALL canonical set (thesis-friendly, robust to naming noise).
CANONICAL_CLASSES: Tuple[str, ...] = (
    "road",
    "sidewalk",
    "lane_marking",   # rarely explicit in OSM, kept for future extensions
    "building",
    "vegetation",
    "traffic_sign",
    "traffic_light",
    "static_prop",
    "parking",
    "unknown",
)

# Default mapping: OSM tags -> canonical class.
# Keep this conservative. You can override/extend via a JSON mapping file.
DEFAULT_MAPPING: Dict[str, str] = {
    # Roads (highway=*)
    "highway:motorway": "road",
    "highway:trunk": "road",
    "highway:primary": "road",
    "highway:secondary": "road",
    "highway:tertiary": "road",
    "highway:residential": "road",
    "highway:service": "road",
    "highway:living_street": "road",
    "highway:unclassified": "road",

    # Sidewalk-ish (OSM is messy; keep a few common ones)
    "highway:footway": "sidewalk",
    "highway:path": "sidewalk",
    "highway:pedestrian": "sidewalk",
    "footway:sidewalk": "sidewalk",

    # Buildings
    "building:yes": "building",
    "building:house": "building",
    "building:apartments": "building",
    "building:commercial": "building",
    "building:industrial": "building",
    "building:garage": "building",

    # Vegetation / landuse / natural
    "landuse:forest": "vegetation",
    "landuse:grass": "vegetation",
    "landuse:meadow": "vegetation",
    "landuse:park": "vegetation",
    "natural:wood": "vegetation",
    "natural:grassland": "vegetation",
    "natural:scrub": "vegetation",

    # Signs / lights (usually nodes)
    "highway:traffic_signals": "traffic_light",
    "traffic_sign:yes": "traffic_sign",
    "highway:stop": "traffic_sign",
    "highway:give_way": "traffic_sign",

    # Parking
    "amenity:parking": "parking",
    "parking:surface": "parking",

    # Props
    "amenity:bench": "static_prop",
    "amenity:fountain": "static_prop",
    "amenity:waste_basket": "static_prop",
}


@dataclass(frozen=True)
class MappingStats:
    counts: Dict[str, int]
    total_elements: int
    unmapped_examples: Dict[str, int]  # tag_key:value -> count (top-ish)


class SemanticMapper:
    """
    Maps OSM tags to a canonical semantic class set.

    Design goals:
    - CARLA-free (safe on HPC)
    - auditable mapping table (thesis-friendly)
    - conservative defaults, overridable via JSON
    """

    def __init__(self, mapping_path: Optional[Path] = None):
        self.default_mapping = dict(DEFAULT_MAPPING)
        self.custom_mapping: Dict[str, str] = {}

        if mapping_path is not None and mapping_path.exists():
            with mapping_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # Expected format: {"key:value": "canonical_class", ...}
            if not isinstance(data, dict):
                raise ValueError("Custom mapping JSON must be an object/dict.")
            self.custom_mapping = {str(k): str(v) for k, v in data.items()}

        self._validate()

    def _validate(self) -> None:
        allowed = set(CANONICAL_CLASSES)
        for src, dst in {**self.default_mapping, **self.custom_mapping}.items():
            if dst not in allowed:
                raise ValueError(
                    f"Mapping entry {src!r} -> {dst!r} uses unknown canonical class. "
                    f"Allowed: {sorted(allowed)}"
                )

    def map_osm_tags(self, tags: Dict[str, str]) -> str:
        """
        Return a single canonical class for an element.

        Rule: first match wins using a small priority list of keys.
        """
        # Priority order: things that should override generic road tags.
        priority_keys = ("traffic_sign", "highway", "footway", "building", "amenity", "landuse", "natural", "parking")

        # Try (key,value) pairs in priority order.
        for k in priority_keys:
            if k in tags:
                kv = f"{k}:{tags[k]}"
                if kv in self.custom_mapping:
                    return self.custom_mapping[kv]
                if kv in self.default_mapping:
                    return self.default_mapping[kv]

        # Fall back: try any tag pair.
        for k, v in tags.items():
            kv = f"{k}:{v}"
            if kv in self.custom_mapping:
                return self.custom_mapping[kv]
            if kv in self.default_mapping:
                return self.default_mapping[kv]

        return "unknown"


def _collect_tags(elem: ET.Element) -> Dict[str, str]:
    tags: Dict[str, str] = {}
    for t in elem.findall("tag"):
        k = t.get("k")
        v = t.get("v")
        if k and v:
            tags[k] = v
    return tags


def analyze_osm_semantics(osm_path: Path, mapper: SemanticMapper, top_unmapped: int = 25) -> MappingStats:
    """
    Parse an .osm XML and compute canonical-class counts across elements (nodes/ways/relations).

    This is NOT geometry-aware â€” itâ€™s semantic *inventory*. Useful for:
    - checking whether the OSM cutout content is stable across runs
    - comparing different OSM cutouts (or OSM versions) consistently
    """
    if not osm_path.exists():
        cwd = Path.cwd()
        raise FileNotFoundError(
            f"OSM file not found: {osm_path}\n"
            f"Current working directory: {cwd}\n\n"
            "Tips:\n"
            "  - Check the relative path is correct from your repo root.\n"
            "  - Try:  dir cities\\ingolstadt   (PowerShell)\n"
            "  - Or:   Get-ChildItem -Recurse -Filter *.osm | Select-Object -First 20 FullName\n"
            "  - Or (bash): find . -name '*.osm' | head\n"
            "  - Or pass an absolute path to --osm.\n"
        )

    tree = ET.parse(osm_path)
    root = tree.getroot()

    counts: Dict[str, int] = {c: 0 for c in CANONICAL_CLASSES}
    unmapped: Dict[str, int] = {}
    total = 0

    for elem in root:
        if elem.tag not in ("node", "way", "relation"):
            continue

        tags = _collect_tags(elem)
        if not tags:
            continue

        total += 1
        cls = mapper.map_osm_tags(tags)
        counts[cls] = counts.get(cls, 0) + 1

        if cls == "unknown":
            # record a compact "signature" for debugging
            # pick the most relevant tag if present, else first tag
            sig_key = None
            for k in ("highway", "building", "amenity", "landuse", "natural", "traffic_sign", "parking"):
                if k in tags:
                    sig_key = f"{k}:{tags[k]}"
                    break
            if sig_key is None:
                k0 = next(iter(tags.keys()))
                sig_key = f"{k0}:{tags[k0]}"
            unmapped[sig_key] = unmapped.get(sig_key, 0) + 1

    # keep only top N unmapped signatures
    unmapped_top = dict(sorted(unmapped.items(), key=lambda kv: kv[1], reverse=True)[:top_unmapped])

    return MappingStats(counts=counts, total_elements=total, unmapped_examples=unmapped_top)


def dump_mapping_template(out_path: Path) -> None:
    """
    Write a starter custom mapping JSON. Users edit this to suit their thesis.
    """
    template = {
        # Example overrides / additions:
        "highway:cycleway": "sidewalk",
        "amenity:parking": "parking",
        "natural:water": "unknown",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, sort_keys=True)



def main() -> int:
    p = argparse.ArgumentParser(description="OSM â†’ canonical semantic inventory (CARLA-free)")
    # --osm and --out are required for analysis runs, but NOT for --write-template.
    p.add_argument("--osm", type=str, default=None, help="Path to .osm (XML) file")
    p.add_argument("--out", type=str, default=None, help="Where to write JSON summary")
    p.add_argument("--mapping", type=str, default=None, help="Optional custom mapping JSON (key:value -> canonical)")
    p.add_argument("--write-template", type=str, default=None, help="Write a starter mapping JSON and exit")
    p.add_argument("--top-unmapped", type=int, default=25, help="How many unmapped tag signatures to show")

    args = p.parse_args()

    if args.write_template:
        dump_mapping_template(Path(args.write_template))
        print(f"âœ… Wrote mapping template to {args.write_template}")
        return 0

    if not args.osm or not args.out:
        p.error("For analysis runs you must provide both --osm and --out (or use --write-template).")

    osm_path = Path(os.path.expandvars(os.path.expanduser(args.osm)))
    out_path = Path(os.path.expandvars(os.path.expanduser(args.out)))
    mapping_path = Path(args.mapping) if args.mapping else None

    mapper = SemanticMapper(mapping_path=mapping_path)
    stats = analyze_osm_semantics(osm_path, mapper, top_unmapped=args.top_unmapped)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "osm_path": str(osm_path),
        "total_tagged_elements": stats.total_elements,
        "canonical_counts": stats.counts,
        "canonical_fractions": {
            k: (v / max(stats.total_elements, 1)) for k, v in stats.counts.items()
        },
        "unmapped_examples_top": stats.unmapped_examples,
        "canonical_classes": list(CANONICAL_CLASSES),
        "mapping_used": {
            "default_entries": len(DEFAULT_MAPPING),
            "custom_entries": len(mapper.custom_mapping),
            "custom_mapping_path": str(mapping_path) if mapping_path else None,
        },
    }
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"âœ… Wrote semantic inventory to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




