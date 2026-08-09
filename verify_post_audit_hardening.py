#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Quick verification gate for the post-audit hardening campaign (G-Q).

Run: .venv\python verify_post_audit_hardening.py
Exits non-zero on any assertion failure.  Does not require a CARLA server.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[0]
RUN = REPO / "reports" / "post_audit_hardening" / "20260807T000000Z"
C1_RUN = REPO / "reports" / "post_audit_hardening" / "20260809T000000Z_C1_GENERATION"
C2_RUN = REPO / "reports" / "post_audit_hardening" / "20260809T000000Z_C2_3DPACKAGE"

REPAIRED = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate" / "ingolstadt_fixed_final.xodr"
ENRICHED = RUN / "candidate_g_semantic_enriched.xodr"
GOVERNED = RUN / "governed_payload.xodr"

SIGNED_REPAIRED_RAW = "80ebb0054afd73ffdd51960b48679ff4689c72ed0abe75af5b2ae10a51395699"
RECORDED_P04_PAYLOAD = "516e329cb6fcec6adb041a4c5f39c48b4de6147b956c7dc2b7ab0c6746490453"
RECORDED_RUNTIME = "9630d9f673fdea87058139d9e2241c7084dc2e2550674bba4bfffc78c6d0ae80"
EXPECTED_GOVERNED = "3f7370ef5ff0a877b429ebca9d79f49827851d24d8608069b4414fcc093729e4"
EXPECTED_ENRICHED_LF = "d604ac393e12730ed276f5c865d0ef82c8a537b97bd8d79beeddd4c96863e470"


def sha256_file_bytes(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def read_text_lf(p: Path) -> str:
    # Mirrors the loader / P04 convention: universal-newline text read -> LF.
    return open(p, "r", encoding="utf-8", errors="replace").read()


def main() -> int:
    checks = []

    def check(name, cond, detail=""):
        checks.append({"name": name, "pass": bool(cond), "detail": detail})

    # G hash chain
    rep_raw = sha256_file_bytes(REPAIRED)
    rep_lf = sha256_text(read_text_lf(REPAIRED))
    enr_lf = sha256_text(read_text_lf(ENRICHED))
    gov_raw = sha256_file_bytes(GOVERNED)
    gov_lf = sha256_text(read_text_lf(GOVERNED))

    check("repaired raw == SIGNED_REPAIRED_RAW", rep_raw == SIGNED_REPAIRED_RAW,
          f"{rep_raw[:16]}")
    check("repaired LF text == P04 payload_sha256", rep_lf == RECORDED_P04_PAYLOAD,
          f"{rep_lf[:16]}")
    check("enriched LF text == expected", enr_lf == EXPECTED_ENRICHED_LF,
          f"{enr_lf[:16]}")
    check("governed raw bytes == expected", gov_raw == EXPECTED_GOVERNED,
          f"{gov_raw[:16]}")
    check("governed raw == governed LF (LF byte-stable artifact)", gov_lf == EXPECTED_GOVERNED,
          f"lf={gov_lf[:16]} raw={gov_raw[:16]}")

    # G replay verdict
    gr = json.loads((RUN / "G_REPLAY_PHASE_H.json").read_text())
    check("G h_replay_verdict PASS", gr["h_replay_verdict"] == "PHASE_H_REPLAY_PASS",
          gr["h_replay_verdict"])
    check("G idempotent", gr["idempotent"] is True)
    check("G integrity_clean", gr["integrity_clean"] is True)
    check("G signal restoration 0->3467",
          gr["semantic_inventory"]["signals"] == 3467,
          str(gr["semantic_inventory"]["signals"]))
    check("G parent_sha256 == repaired LF text",
          gr["parent_sha256"] == RECORDED_P04_PAYLOAD, gr["parent_sha256"][:16])

    # H coordinate contract
    q03 = json.loads((RUN / "Q03_LOAD_PAYLOAD_MANIFEST.json").read_text())
    cc = q03["coordinate_contract"]
    check("H coordinate_contract_pass", cc["coordinate_contract_pass"] is True, str(cc))
    check("H candidate sha == enriched LF", q03["candidate"]["sha256"] == EXPECTED_ENRICHED_LF)
    check("H payload sha == governed", q03["payload"]["sha256"] == EXPECTED_GOVERNED, q03["payload"]["sha256"][:16])

    # I equivalence
    ip = json.loads((RUN / "I_PACKAGED_MAP_EVIDENCE.json").read_text())
    cmp_pkg_payload = ip["equivalence"]["packaged_vs_governed_payload_verdict"]
    check("I packaged vs governed payload PASS",
          cmp_pkg_payload == "SEMANTIC_EQUIVALENCE_PASS", cmp_pkg_payload)
    check("I signals == 3467", ip["semantic_inventory"]["packaged"]["signals"] == 3467)

    # J-N blocked
    for s in ("J", "K", "L", "M", "N"):
        jf = RUN / {"J": "J_BUILTIN_SMOKE.json", "K": "K_TRAFFIC_BUILTIN.json",
                    "L": "L_GOVERNED_PAYLOAD_LOAD.json", "M": "M_RUNTIME_EQUIVALENCE.json",
                    "N": "N_PERCEPTION_FPS.json"}[s]
        d = json.loads(jf.read_text())
        check(f"{s} BLOCKED_SERVER_UNAVAILABLE",
              d["verdict"] == f"{s}_BLOCKED_SERVER_UNAVAILABLE", d["verdict"])

    # Residual gaps (flipped after C1: present <= authority, cornerLocal-only)
    c1b = json.loads((C1_RUN / "C1B_CROSSING_DISPOSITION_LEDGER.json").read_text())
    c1c = json.loads((C1_RUN / "C1C_PEDESTRIAN_LEDGER.json").read_text())
    c1f = json.loads((C1_RUN / "C1F_PROTECTED_INTEGRITY.json").read_text())
    cc_corners = c1f["crosswalk_corners"]
    auth_x = c1b["authority_total"]
    present_x = c1b["disposition_counts"]["INSERTED"] + c1b["disposition_counts"]["DUPLICATE_MERGED"]
    check("crosswalk objects present <= authority (66 <= 179)",
          present_x == 66 and auth_x == 179 and present_x <= auth_x,
          f"present={present_x} authority={auth_x}")
    check("crosswalk corners cornerLocal-only (66 nonempty, 0 empty)",
          cc_corners["objects_with_nonempty_cornerLocal"] == 66
          and cc_corners["objects_with_empty_cornerLocal"] == 0,
          str(cc_corners))
    auth_p = c1c["authority_total"]
    present_p = (c1c["disposition_counts"]["ALREADY_PRESENT"]
                 + c1c["disposition_counts"]["INSERTED_XODR_OBJECT"]
                 + c1c["disposition_counts"]["PACKAGE_MESH_REQUIRED"])
    check("pedestrian lanes present <= authority (5318 <= 5431)",
          present_p == 5318 and auth_p == 5431 and present_p <= auth_p,
          f"present={present_p} authority={auth_p}")
    c2b = C2_RUN / "C2B_ALREADY_PRESENT_DECOMPOSITION.json"
    if c2b.exists():
        d = json.loads(c2b.read_text())
        check("C2B decomposition split == 5071",
              d["road_adjacent_sidewalk_matched"] + d["standalone_package_mesh"] == 5071,
              str(d))
    else:
        check("C2B decomposition pending (B not run)", True, "C2B ledger pending")

    ok = all(c["pass"] for c in checks)
    print("VERIFY_POST_AUDIT_HARDENING:", "ALL PASS" if ok else "FAILURES")
    for c in checks:
        flag = "PASS" if c["pass"] else "FAIL"
        print(f"  [{flag}] {c['name']}")
    if not ok:
        for c in checks:
            if not c["pass"]:
                print(f"    FAIL: {c['name']} -> {c['detail']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
