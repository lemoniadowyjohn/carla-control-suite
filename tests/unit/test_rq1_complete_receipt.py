"""Subprocess coverage for the executable RQ1 complete receipt CLI."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from ultimate_pipeline.core.terminal_authority import compute_settings_digest


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "rq1_complete_receipt.py"


def _write_xodr(path: Path, *, crlf: bool = False) -> None:
    sep = "\r\n" if crlf else "\n"
    path.write_bytes(
        sep.join(
            (
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<OpenDRIVE><header north="1" south="0" east="1" west="0"/>',
                '<road id="1" length="12.5" junction="-1"><lanes><laneSection s="0"><left><lane id="1"/></left><center><lane id="0"/></center><right><lane id="-1"/></right></laneSection></lanes></road>',
                "</OpenDRIVE>",
                "",
            )
        ).encode("utf-8")
    )


def _write_sitecustomize(stub_dir: Path) -> None:
    stub_dir.joinpath("sitecustomize.py").write_text(
        '''
import hashlib
import os
import sys
import types
from pathlib import Path

root_path = Path(os.environ["RQ1_RECEIPT_REPO"]) / "ultimate_pipeline"
root = types.ModuleType("ultimate_pipeline")
root.__path__ = [str(root_path)]
sys.modules["ultimate_pipeline"] = root

carla_tools = types.ModuleType("ultimate_pipeline.carla_tools")
carla_tools.__path__ = []
sys.modules["ultimate_pipeline.carla_tools"] = carla_tools
registry = types.ModuleType("ultimate_pipeline.carla_tools.map_registry")
def verify_pinned_map(_name):
    path = Path(os.environ["RQ1_RECEIPT_INPUT"])
    return {"verification_status": "VERIFIED", "resolved_path": str(path), "sha256_actual": hashlib.sha256(path.read_bytes()).hexdigest()}
registry.verify_pinned_map = verify_pinned_map
sys.modules["ultimate_pipeline.carla_tools.map_registry"] = registry

config = types.ModuleType("ultimate_pipeline.config")
config.__path__ = []
sys.modules["ultimate_pipeline.config"] = config
settings = types.ModuleType("ultimate_pipeline.config.settings")
class Settings:
    INPUT_XODR = "original-input.xodr"
    BASE_OUTPUT_DIR = "original-output"
    QA_AUTOVIS = True
    KEEP = "unchanged"
settings.SETTINGS = Settings()
sys.modules["ultimate_pipeline.config.settings"] = settings

pipeline_module = types.ModuleType("ultimate_pipeline.main_pipeline")
class MainPipeline:
    def __init__(self, settings):
        self.settings = settings
        self.map_acceptance = None
    def run(self):
        if os.environ.get("RQ1_RECEIPT_FAIL_PIPELINE") == "1":
            raise RuntimeError("fixture pipeline failure")
        out = Path(self.settings.BASE_OUTPUT_DIR) / "pipeline-output"
        out.mkdir(parents=True, exist_ok=True)
        final_xodr = out / "final.xodr"
        final_xodr.write_text("<OpenDRIVE><header/><road id='2' length='7' junction='-1'/></OpenDRIVE>\\n", encoding="utf-8")
        final_sha = hashlib.sha256(final_xodr.read_bytes()).hexdigest()
        self.map_acceptance = {
            "valid_for_experiments": True,
            "final_xodr_path": str(final_xodr),
            "final_xodr_sha256": final_sha,
            "payload_sha256": "a" * 64,
            "metrics": {"road_count": 1, "junction_count": 0, "lane_count": 0, "buildings_count": 3},
            "linked_artifact_sha256": {"tileset_digest": "b" * 64},
        }
        return str(out)
pipeline_module.MainPipeline = MainPipeline
sys.modules["ultimate_pipeline.main_pipeline"] = pipeline_module
'''.lstrip(),
        encoding="utf-8",
    )


def _run_cli(tmp_path: Path, *args: str, fail_pipeline: bool = False) -> subprocess.CompletedProcess[str]:
    input_xodr = tmp_path / "input.xodr"
    if not input_xodr.exists():
        _write_xodr(input_xodr, crlf=True)
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir(exist_ok=True)
    _write_sitecustomize(stub_dir)
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": os.pathsep.join((str(stub_dir), str(REPO), env.get("PYTHONPATH", ""))),
            "RQ1_RECEIPT_REPO": str(REPO),
            "RQ1_RECEIPT_INPUT": str(input_xodr),
        }
    )
    if fail_pipeline:
        env["RQ1_RECEIPT_FAIL_PIPELINE"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=REPO, env=env, text=True, capture_output=True, check=False
    )


def test_cli_writes_complete_receipt_from_real_writer_with_mocked_boundaries(tmp_path: Path):
    output_base = tmp_path / "runs"
    result = _run_cli(tmp_path, "7", str(output_base))

    assert result.returncode == 0, result.stderr
    receipt_path = output_base / "run_07" / "rq1_run_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    input_xodr = tmp_path / "input.xodr"
    expected_settings = SimpleNamespace(
        INPUT_XODR=str(input_xodr),
        BASE_OUTPUT_DIR=str(output_base / "run_07"),
        QA_AUTOVIS=False,
        KEEP="unchanged",
    )

    assert receipt["schema"] == "rq1_run_receipt/v1"
    assert receipt["status"] == "ok"
    assert receipt["input_sha256"] == hashlib.sha256(input_xodr.read_bytes()).hexdigest()
    assert "xodr_sha256" not in receipt["structural_signature"]
    assert receipt["structural_signature"]["road_count"] == 1
    assert receipt["feature_counts"]["road_count"] == 1
    assert receipt["topology_counts"]["road_count"] == 1
    assert receipt["tileset_digest"] == "b" * 64
    assert receipt["settings_hash"] == compute_settings_digest(expected_settings)
    canonical = dict(receipt)
    canonical["final_receipt_digest"] = ""
    assert receipt["final_receipt_digest"] == hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def test_cli_pipeline_failure_is_nonzero_and_writes_no_success_receipt(tmp_path: Path):
    output_base = tmp_path / "runs"
    result = _run_cli(tmp_path, "4", str(output_base), fail_pipeline=True)

    assert result.returncode != 0
    assert "fixture pipeline failure" in result.stderr
    assert not (output_base / "run_04" / "rq1_run_receipt.json").exists()


def test_cli_rejects_invalid_run_index(tmp_path: Path):
    result = _run_cli(tmp_path, "not-an-index", str(tmp_path / "runs"))

    assert result.returncode != 0
    assert "invalid int value" in result.stderr
