# ultimate_pipeline/semantics/semantic_mapper.py is a standalone dev CLI tool
# (OSM tag -> canonical class inventory), never imported by the live pipeline
# (grep-confirmed: zero real imports anywhere in the repo), but directly
# runnable by a human via `python -m ultimate_pipeline.semantics.semantic_mapper`.
# Had zero prior test coverage. main() computed SemanticMapper + ran
# analyze_osm_semantics TWICE in a row (identical copy-pasted calls) --
# harmless in output (idempotent) but silently doubled the cost of parsing
# and analyzing the input .osm file on every CLI invocation. Fixed by
# removing the duplicate block.
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.semantics.semantic_mapper import (
    CANONICAL_CLASSES,
    DEFAULT_MAPPING,
    SemanticMapper,
    analyze_osm_semantics,
    dump_mapping_template,
    main,
)


# ---------------------------------------------------------------------------
# SemanticMapper.map_osm_tags
# ---------------------------------------------------------------------------


def test_default_mapping_entries_all_target_canonical_classes():
    allowed = set(CANONICAL_CLASSES)
    for src, dst in DEFAULT_MAPPING.items():
        assert dst in allowed, f"{src} -> {dst} not in {allowed}"


def test_map_osm_tags_direct_hit():
    mapper = SemanticMapper()
    assert mapper.map_osm_tags({"highway": "residential"}) == "road"


def test_map_osm_tags_unknown_tags_return_unknown():
    mapper = SemanticMapper()
    assert mapper.map_osm_tags({"foo": "bar"}) == "unknown"


def test_map_osm_tags_priority_order_traffic_sign_over_highway():
    # priority_keys puts "traffic_sign" before "highway"
    mapper = SemanticMapper()
    tags = {"highway": "residential", "traffic_sign": "yes"}
    assert mapper.map_osm_tags(tags) == "traffic_sign"


def test_map_osm_tags_fallback_scans_all_tags_when_no_priority_key_matches():
    mapper = SemanticMapper()
    # "footway" as a top-level key (not "highway:footway") isn't in the
    # priority list's exact key set for that value, but the fallback loop
    # over all (k, v) pairs should still find it via DEFAULT_MAPPING.
    tags = {"footway": "sidewalk"}
    assert mapper.map_osm_tags(tags) == "sidewalk"


def test_custom_mapping_overrides_default():
    mapper = SemanticMapper()
    mapper.custom_mapping["highway:residential"] = "unknown"
    assert mapper.map_osm_tags({"highway": "residential"}) == "unknown"


def test_custom_mapping_json_loaded_from_file(tmp_path):
    mapping_path = tmp_path / "custom.json"
    mapping_path.write_text(
        json.dumps({"highway:cycleway": "sidewalk"}), encoding="utf-8"
    )
    mapper = SemanticMapper(mapping_path=mapping_path)
    assert mapper.custom_mapping == {"highway:cycleway": "sidewalk"}
    assert mapper.map_osm_tags({"highway": "cycleway"}) == "sidewalk"


def test_custom_mapping_missing_file_is_ignored(tmp_path):
    mapper = SemanticMapper(mapping_path=tmp_path / "does_not_exist.json")
    assert mapper.custom_mapping == {}


def test_custom_mapping_non_dict_json_raises(tmp_path):
    mapping_path = tmp_path / "bad.json"
    mapping_path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    with pytest.raises(ValueError):
        SemanticMapper(mapping_path=mapping_path)


def test_custom_mapping_unknown_canonical_class_raises(tmp_path):
    mapping_path = tmp_path / "bad_class.json"
    mapping_path.write_text(
        json.dumps({"highway:foo": "not_a_real_class"}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        SemanticMapper(mapping_path=mapping_path)


# ---------------------------------------------------------------------------
# analyze_osm_semantics
# ---------------------------------------------------------------------------


def _write_osm(path: Path, elements_xml: str) -> None:
    path.write_text(
        f'<?xml version="1.0"?><osm version="0.6">{elements_xml}</osm>',
        encoding="utf-8",
    )


def test_analyze_osm_semantics_missing_file_raises(tmp_path):
    mapper = SemanticMapper()
    with pytest.raises(FileNotFoundError):
        analyze_osm_semantics(tmp_path / "missing.osm", mapper)


def test_analyze_osm_semantics_counts_by_canonical_class(tmp_path):
    p = tmp_path / "map.osm"
    _write_osm(
        p,
        """
        <node id="1"><tag k="highway" v="residential"/></node>
        <node id="2"><tag k="highway" v="residential"/></node>
        <way id="3"><tag k="building" v="yes"/></way>
        <node id="4"></node>
        """,
    )
    mapper = SemanticMapper()
    stats = analyze_osm_semantics(p, mapper)

    assert stats.total_elements == 3  # untagged node excluded
    assert stats.counts["road"] == 2
    assert stats.counts["building"] == 1
    assert stats.counts["vegetation"] == 0


def test_analyze_osm_semantics_records_unmapped_signatures(tmp_path):
    p = tmp_path / "map.osm"
    _write_osm(
        p,
        """
        <node id="1"><tag k="amenity" v="totally_unknown_thing"/></node>
        """,
    )
    mapper = SemanticMapper()
    stats = analyze_osm_semantics(p, mapper, top_unmapped=5)

    assert stats.counts["unknown"] == 1
    assert "amenity:totally_unknown_thing" in stats.unmapped_examples


# ---------------------------------------------------------------------------
# dump_mapping_template
# ---------------------------------------------------------------------------


def test_dump_mapping_template_writes_valid_json(tmp_path):
    out = tmp_path / "nested" / "template.json"
    dump_mapping_template(out)

    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "highway:cycleway" in data


# ---------------------------------------------------------------------------
# main() -- regression test for the double-computation bug
# ---------------------------------------------------------------------------


def test_main_analyzes_osm_exactly_once(tmp_path, monkeypatch):
    osm_path = tmp_path / "in.osm"
    _write_osm(osm_path, '<node id="1"><tag k="highway" v="residential"/></node>')
    out_path = tmp_path / "out.json"

    call_count = {"n": 0}
    real_analyze = analyze_osm_semantics

    def _counting_analyze(*args, **kwargs):
        call_count["n"] += 1
        return real_analyze(*args, **kwargs)

    monkeypatch.setattr(
        "ultimate_pipeline.semantics.semantic_mapper.analyze_osm_semantics",
        _counting_analyze,
    )
    monkeypatch.setattr(
        sys, "argv", ["semantic_mapper.py", "--osm", str(osm_path), "--out", str(out_path)]
    )

    rc = main()

    assert rc == 0
    assert call_count["n"] == 1
    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["total_tagged_elements"] == 1


def test_main_write_template_mode(tmp_path, monkeypatch):
    template_path = tmp_path / "template.json"
    monkeypatch.setattr(
        sys, "argv", ["semantic_mapper.py", "--write-template", str(template_path)]
    )

    rc = main()

    assert rc == 0
    assert template_path.exists()


def test_main_requires_osm_and_out_without_write_template(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["semantic_mapper.py"])
    with pytest.raises(SystemExit):
        main()
