from pathlib import Path

def infer_run_root_from_auto_meta(auto_meta: Path) -> Path:
    p = auto_meta.resolve()
    for parent in p.parents:
        if parent.name == "domain_gap":
            return parent.parent
    return p.parent

def test_infer_run_root_when_meta_in_domain_gap(tmp_path: Path):
    run = tmp_path/"ultimate_pipeline_out"/"batch_x"/"run_005"
    meta = run/"domain_gap"/"auto_tiles_promoted"/"tile_metadata.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text("{}", encoding="utf-8")
    assert infer_run_root_from_auto_meta(meta) == run

def test_infer_run_root_when_meta_top_level(tmp_path: Path):
    run = tmp_path/"ultimate_pipeline_out"/"batch_x"/"run_005"
    meta = run/"tile_metadata.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text("{}", encoding="utf-8")
    assert infer_run_root_from_auto_meta(meta) == run
