"""Adversarial offline tests for exact-run CI dependency authority."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("ci_needs_gate", ROOT / "tools" / "ci_needs_gate.py")
assert SPEC is not None and SPEC.loader is not None
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)
SHA = "a" * 40
ALT_SHA = "b" * 40


def good():
    return {k: {"result": "success", "outputs": {}} for k in ci.REQUIRED}


class NeedsGateTests(unittest.TestCase):
    def test_complete_same_sha_only_offline_pass(self):
        result = ci.verify_needs(good(), expected_sha=SHA, checkout_sha=SHA)
        self.assertEqual(result["verdict"], "PASS_OFFLINE_PREDECESSORS_ONLY")
        self.assertEqual(result["runtime_certification"], "NOT_RUN")
        self.assertEqual(result["workflow_sha"], SHA)
        self.assertEqual(set(result["required_jobs"]), ci.REQUIRED)

    def test_each_unacceptable_job_outcome_rejected(self):
        for outcome in ("failure", "cancelled", "skipped", "neutral", "timed_out", "action_required", "pending", "INCOMPLETE", "NOT_RUN", "SUCCESS", None, True):
            with self.subTest(outcome=outcome):
                data = good()
                data["offline-tests"]["result"] = outcome
                with self.assertRaises(ci.CIGateError):
                    ci.verify_needs(data, expected_sha=SHA, checkout_sha=SHA)

    def test_every_missing_predecessor_is_rejected(self):
        for k in ci.REQUIRED:
            with self.subTest(k=k):
                data = good()
                del data[k]
                with self.assertRaisesRegex(ci.CIGateError, "missing="):
                    ci.verify_needs(data, expected_sha=SHA, checkout_sha=SHA)

    def test_unexpected_predecessor_rejected(self):
        data = good()
        data["malicious-extra-job"] = {"result": "success"}
        with self.assertRaises(ci.CIGateError):
            ci.verify_needs(data, expected_sha=SHA, checkout_sha=SHA)

    def test_bad_payload_shapes_rejected(self):
        for payload in (None, [], "success", 1, True):
            with self.subTest(payload=payload):
                with self.assertRaises(ci.CIGateError):
                    ci.verify_needs(payload, expected_sha=SHA, checkout_sha=SHA)
        for bad in (None, [], "success", 1, {"result": None}, {"result": "PASS"}):
            with self.subTest(bad=bad):
                payload = good()
                payload["offline-tests"] = bad
                with self.assertRaises(ci.CIGateError):
                    ci.verify_needs(payload, expected_sha=SHA, checkout_sha=SHA)

    def test_sha_mismatch_or_malformed_fails_closed(self):
        for exp, obs in ((SHA, ALT_SHA), ("", SHA), (SHA, ""), ("x" * 40, SHA), (SHA.upper(), SHA), (SHA, SHA.upper())):
            with self.subTest(exp=exp, obs=obs):
                with self.assertRaises(ci.CIGateError):
                    ci.verify_needs(good(), expected_sha=exp, checkout_sha=obs)

    def test_process_reports_failure_on_invalid_json_and_success_with_mocked_checkout(self):
        with patch.dict(os.environ, {"CI_NEEDS_JSON": "not-json", "CI_EXPECTED_SHA": SHA}):
            with patch.object(ci.subprocess, "check_output", return_value=SHA):
                self.assertEqual(ci.main(), 2)
        with patch.dict(os.environ, {"CI_NEEDS_JSON": json.dumps(good()), "CI_EXPECTED_SHA": SHA}):
            with patch.object(ci.subprocess, "check_output", return_value=SHA):
                self.assertEqual(ci.main(), 0)

    def test_workflow_wires_always_and_exact_predecessor_gate(self):
        path = ROOT / ".github" / "workflows" / "tests.yml"
        self.assertTrue(path.is_file(), "production workflow is required for this test")
        data = path.read_text(encoding="utf-8")
        block = data.split("\n  offline-release-gate:\n", 1)[1].split("\n  windows-single-writer:\n", 1)[0]
        self.assertIn("if: ${{ always() }}", block)
        self.assertIn("CI_NEEDS_JSON: ${{ toJSON(needs) }}", block)
        self.assertIn("CI_EXPECTED_SHA: ${{ github.sha }}", block)
        self.assertIn("python tools/ci_needs_gate.py", block)
        for job in ci.REQUIRED:
            self.assertIn("- " + job, block)


if __name__ == "__main__":
    unittest.main()
