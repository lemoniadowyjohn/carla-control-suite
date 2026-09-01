# ultimate_pipeline/domain_gap/run_domain_gap_sweep.py::_find_auto_xodr() --
# confirmed dead-to-pipeline (zero references anywhere) but a human-runnable
# standalone script (`if __name__ == "__main__": run_domain_gap_sweep()`)
# whose entire purpose is generating RQ1 domain-gap evidence
# (run_full_domain_gap(manual_xodr=..., auto_xodr=auto_xodr, ...)).
#
# Same bug already found and fixed in the near-identical
# run_gap_ablation_experiment.py::_find_auto_xodr() (fixed @93518290): used
# `next(os.listdir(...))` -- os.listdir()'s order is arbitrary/OS-dependent,
# so which 08_final*.xodr variant fed the domain-gap computation was
# genuinely non-deterministic. Extracted into a testable helper and fixed
# to mtime-newest, matching the established convention.
from __future__ import annotations

import time
from pathlib import Path

from ultimate_pipeline.domain_gap.run_domain_gap_sweep import _find_auto_xodr


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
