from pathlib import Path

from carla_map_quality_toolkit.io import file_provenance, sha256_file

FIXTURES = Path(__file__).parent / "fixtures"


def test_file_hash_is_stable_and_exposed_as_provenance() -> None:
    fixture = FIXTURES / "synthetic.osm"
    digest = sha256_file(fixture)
    assert len(digest) == 64
    assert digest == sha256_file(fixture)
    provenance = file_provenance(fixture, label="osm")
    assert provenance["osm_name"] == "synthetic.osm"
    assert provenance["osm_sha256"] == digest


def test_file_hash_changes_when_content_changes(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("synthetic-a", encoding="utf-8")
    second.write_text("synthetic-b", encoding="utf-8")
    assert sha256_file(first) != sha256_file(second)
