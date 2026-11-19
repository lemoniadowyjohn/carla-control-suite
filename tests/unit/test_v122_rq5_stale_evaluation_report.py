"""V122: success requires a report written by the current evaluator invocation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ultimate_pipeline import run_generalization_experiments as rq5


@pytest.mark.parametrize("kind", ["sim", "real"])
def test_old_condition_report_cannot_satisfy_new_invocation(tmp_path, monkeypatch, kind):
    condition = "generated_k_k001"
    legacy = tmp_path / "out" / "eval" / condition
    legacy.mkdir(parents=True)
    filename = "sim_labeled_eval.json" if kind == "sim" else "real_u_eval_report.json"
    stale = legacy / filename
    stale.write_text(json.dumps({"status": "ok", "model_sha256": "m" * 64}), encoding="utf-8")

    monkeypatch.setattr(rq5, "_run_subprocess", lambda *a, **kw: 0)
    if kind == "sim":
        result = rq5.eval_sim_labeled(
            condition, tmp_path / "model.pt", tmp_path / "eval_data",
            "front_left_camera", tmp_path / "out", "cpu", tmp_path / "logs",
        )
    else:
        result = rq5.eval_real_unlabeled(
            condition, tmp_path / "model.pt", tmp_path / "real_data",
            tmp_path / "out", "cpu", tmp_path / "logs",
        )
    assert result["ok"] is False
    assert result["status"] == "missing_report"
    assert result["evaluation_invocation_id"]
    assert Path(result["evaluation_report_path"]) != stale
    assert not Path(result["evaluation_report_path"]).exists()
    assert stale.read_text(encoding="utf-8").find('"status": "ok"') >= 0


@pytest.mark.parametrize("kind", ["sim", "real"])
def test_two_invocations_have_distinct_reports_and_preserve_prior_evidence(tmp_path, monkeypatch, kind):
    reports = []
    def fake_child(cmd, log_file=None, env=None):
        p = Path(cmd[cmd.index("--out-json") + 1])
        p.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        reports.append(p)
        return 0
    monkeypatch.setattr(rq5, "_run_subprocess", fake_child)
    if kind == "sim":
        run = lambda: rq5.eval_sim_labeled(
            "generated_k_k003", tmp_path / "model.pt", tmp_path / "eval",
            "front_left_camera", tmp_path / "out", "cpu", tmp_path / "logs",
        )
    else:
        run = lambda: rq5.eval_real_unlabeled(
            "generated_k_k003", tmp_path / "model.pt", tmp_path / "real",
            tmp_path / "out", "cpu", tmp_path / "logs",
        )
    a = run()
    b = run()
    assert a["ok"] and b["ok"]
    assert a["evaluation_invocation_id"] != b["evaluation_invocation_id"]
    assert a["evaluation_report_path"] != b["evaluation_report_path"]
    assert len(reports) == 2
    assert all(path.exists() for path in reports)
