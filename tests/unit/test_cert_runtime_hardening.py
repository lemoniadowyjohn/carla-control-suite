from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.verify_candidate_digest import sha256_file
from ultimate_pipeline.tools.cert_runtime.runtime_config import (
    assert_candidate_consistency,
    resolve_cert_runtime_config,
)
from ultimate_pipeline.tools.cert_runtime.run_p4_equiv import collect_runtime_evidence
from ultimate_pipeline.tools.cert_runtime.write_p4_evidence import package_p4_evidence


def test_resolver_prefers_cli_over_env(tmp_path):
    env = {
        "UP_CERT_CANDIDATE_XODR": str(tmp_path / "env_candidate.xodr"),
        "UP_CERT_RUNID": "20260814T000000Z",
        "UP_CERT_PHASE_L_DIR": str(tmp_path / "env_phase_l"),
        "UP_CERT_P4_DIR": str(tmp_path / "env_p4"),
    }
    cfg = resolve_cert_runtime_config(
        candidate_xodr=tmp_path / "cli_candidate.xodr",
        run_id="20260814T010101Z",
        phase_l_dir=tmp_path / "cli_phase_l",
        p4_dir=tmp_path / "cli_p4",
        env=env,
    )

    assert cfg.candidate_xodr == tmp_path / "cli_candidate.xodr"
    assert cfg.run_id == "20260814T010101Z"
    assert cfg.phase_l_dir == tmp_path / "cli_phase_l"
    assert cfg.p4_dir == tmp_path / "cli_p4"


def test_resolver_uses_env_when_cli_missing(tmp_path):
    env = {
        "UP_CERT_CANDIDATE_XODR": str(tmp_path / "env_candidate.xodr"),
        "UP_CERT_RUNID": "20260814T020202Z",
        "UP_CERT_PHASE_L_DIR": str(tmp_path / "env_phase_l"),
        "UP_CERT_P4_DIR": str(tmp_path / "env_p4"),
    }
    cfg = resolve_cert_runtime_config(env=env)

    assert cfg.candidate_xodr == tmp_path / "env_candidate.xodr"
    assert cfg.run_id == "20260814T020202Z"
    assert cfg.phase_l_dir == tmp_path / "env_phase_l"
    assert cfg.p4_dir == tmp_path / "env_p4"


def test_assert_candidate_consistency_passes(tmp_path):
    candidate = tmp_path / "candidate.xodr"
    candidate.write_text("<OpenDRIVE><road id=\"1\" length=\"1.0\"/></OpenDRIVE>", encoding="utf-8")
    digest = sha256_file(candidate)

    assert assert_candidate_consistency(
        p4_rep_sha256=digest,
        phase_l_l2_sha256=digest,
        candidate_xodr=candidate,
    ) == digest


def test_assert_candidate_consistency_raises_on_mismatch(tmp_path):
    candidate = tmp_path / "candidate.xodr"
    candidate.write_text("<OpenDRIVE><road id=\"1\" length=\"1.0\"/></OpenDRIVE>", encoding="utf-8")

    with pytest.raises(RuntimeError, match="candidate consistency preflight failed"):
        assert_candidate_consistency(
            p4_rep_sha256="0" * 64,
            phase_l_l2_sha256="1" * 64,
            candidate_xodr=candidate,
        )


def test_collect_runtime_evidence_runs_with_synthetic_loader(tmp_path):
    source = tmp_path / "source.xodr"
    repaired = tmp_path / "repaired.xodr"
    xodr_text = "<OpenDRIVE><road id=\"1\"/></OpenDRIVE>"
    source.write_text(xodr_text, encoding="utf-8")
    repaired.write_text(xodr_text, encoding="utf-8")

    class FakeMap:
        name = "Carla/Maps/OpenDriveMap"

        def to_opendrive(self):
            return xodr_text

    class FakeWorld:
        def get_map(self):
            return FakeMap()

    class FakeClient:
        def set_timeout(self, value):
            self.timeout = value

    def fake_loader(client, path, **kwargs):
        assert Path(path) == repaired
        return FakeWorld()

    payload = collect_runtime_evidence(
        source_xodr=source,
        repaired_xodr=repaired,
        client=FakeClient(),
        load_world_fn=fake_loader,
        log_fn=lambda *_: None,
    )

    assert payload["status"] == "OK"
    assert payload["rep_sha256"] == sha256_file(repaired)
    assert payload["runtime_to_opendrive_sha256"]


def test_package_p4_evidence_runs_on_synthetic_payload(tmp_path):
    runtime = tmp_path / "_p4_runtime_evidence.json"
    runtime.write_text(
        json.dumps(
            {
                "inventory": {
                    "source": {"lane_sections": 1, "driving_lanes": 1},
                    "runtime": {"lane_sections": 1, "driving_lanes": 1},
                    "missing_roads": [],
                    "unexpected_roads": [],
                    "missing_junctions": [],
                    "unexpected_junctions": [],
                },
                "src_sha256": "a" * 64,
                "rep_sha256": "a" * 64,
                "runtime_to_opendrive_sha256": "a" * 64,
            }
        ),
        encoding="utf-8",
    )

    run_dir = package_p4_evidence(runtime_evidence_path=runtime, p4_dir=tmp_path / "out")
    assert run_dir == tmp_path / "out"
    assert (run_dir / "P04_RAW_RUNTIME_EVIDENCE.json").exists()
    assert (run_dir / "P13_RUNTIME_INVENTORY_METHODS.md").exists()

