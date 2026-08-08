#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R13 - governed payload identity guard tests (offline).

Proves the hardened writer transaction (temp -> fsync -> reopen-compute ->
atomic rename -> reopen-verify) cannot diverge from disk bytes and that the
independent verifier flags any later divergence (the pre-C0 quarantine class).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
R13 = REPO / "reports" / "post_audit_hardening" / "20260808T000000Z_C0_REMEDIATION"

sys.path.insert(0, str(REPO))
from phase_q.governed_payload import (  # noqa: E402
    IDENTITY_GUARD, atomic_write_payload_bytes, verify_payload_identity,
    IdentityError, IdentityVerificationError)

PAYLOAD = ("<?xml version=\"1.0\"?>\n<OpenDRIVE>\n  <header/>\n  <road>\n"
           "    <link/>\n    <planView/>\n  </road>\n</OpenDRIVE>\n").encode("utf-8")


def test_atomic_write_identity_record(tmp_path):
    p = tmp_path / "guard_ok.xodr"
    rec = atomic_write_payload_bytes(str(p), PAYLOAD)
    assert rec["identity_pass"] is True
    assert rec["guard"] == IDENTITY_GUARD
    assert rec["declared_sha256"] == rec["disk_sha256"] == rec["post_rename_sha256"]
    assert rec["declared_size"] == rec["disk_size"] == rec["post_rename_size"]
    assert p.read_bytes() == PAYLOAD


def test_verify_payload_identity_pass(tmp_path):
    p = tmp_path / "guard_verify.xodr"
    rec = atomic_write_payload_bytes(str(p), PAYLOAD)
    v = verify_payload_identity(str(p), rec["declared_sha256"], rec["declared_size"])
    assert v["identity_pass"] is True


def test_tamper_detected(tmp_path):
    p = tmp_path / "guard_tampered.xodr"
    rec = atomic_write_payload_bytes(str(p), PAYLOAD)
    tampered = bytearray(p.read_bytes())
    tampered[-10] ^= 0x01
    p.write_bytes(bytes(tampered))
    with pytest.raises(IdentityVerificationError):
        verify_payload_identity(str(p), rec["declared_sha256"], rec["declared_size"])


def test_identity_error_hierarchy():
    assert issubclass(IdentityVerificationError, IdentityError)
    assert issubclass(IdentityError, RuntimeError)


def test_r13b_evidence_passes():
    ev = json.loads((R13 / "R13B_GOVERNED_PAYLOAD_IDENTITY_GUARD.json").read_text())
    assert ev["verdict"] == "GOVERNED_PAYLOAD_IDENTITY_GUARD_OK"
    assert ev["write_transaction_pass"] is True
    assert ev["tamper_detection"]["pass"] is True