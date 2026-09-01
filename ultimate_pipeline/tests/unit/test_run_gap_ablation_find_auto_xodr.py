# ultimate_pipeline/domain_gap/run_gap_ablation_experiment.py::_find_auto_xodr() --
# confirmed dead-to-pipeline (zero references anywhere) but a human-runnable
# standalone script (`if __name__ == "__main__": run_domain_gap_ablation(...)`).
# Same bug class already found and fixed in artifact_locator.py::find_final_xodr()
# and stage_gate_regression.py::_find_stage_xodr(), but worse here: used
# `next(os.listdir(out_dir))` -- os.listdir()'s order is arbitrary/OS-dependent,
# not even a deterministic (if wrong) lexicographic sort, so which
# 08_final*.xodr variant got picked was genuinely non-deterministic. Fixed to
# mtime-newest, matching the established convention.
from __future__ import annotations

import time
from pathlib import Path

from ultimate_pipeline.domain_gap.run_gap_ablation_experiment import _find_auto_xodr


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_picks_newest_variant_not_arbitrary_listdir_order(tmp_path: Path):
    _write(tmp_path / "08_final_X.xodr", "PRE-REPAIR (stale)")
    time.sleep(0.02)
    _write(tmp_path / "08_final_X_semantic.xodr", "PRE-REPAIR (stale copy)")
    time.sleep(0.02)
    _write(tmp_path / "08_final_X_laneSectionFixed.xodr", "AUTHORITATIVE (repaired)")
    time.sleep(0.02)
    _write(tmp_path / "08_final_X_semantic.xodr", "AUTHORITATIVE (repaired, refreshed copy)")

    result = _find_auto_xodr(str(tmp_path))

    assert Path(result).read_text(encoding="utf-8") == "AUTHORITATIVE (repaired, refreshed copy)"


def test_single_candidate_still_works(tmp_path: Path):
    _write(tmp_path / "08_final_only.xodr", "the only one")

    result = _find_auto_xodr(str(tmp_path))

    assert Path(result).read_text(encoding="utf-8") == "the only one"
