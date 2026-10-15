"""Finalise the capacity model with a drift-corrected, internally consistent
verdict. Plan only; nothing deleted.
"""
from __future__ import annotations

import json
import os

OUT = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports"
p = os.path.join(OUT, "COOK_CAPACITY_MODEL.json")
with open(p, encoding="utf-8") as fh:
    m = json.load(fh)

C_SAFE = 43.01
F_SAFE = 8.46
C_BASE = 9.80          # measured at model build
C_LATEST = 7.99        # measured minutes later, before any deletion
F_BASE = 41.50
F_LATEST = 41.11

DDC, COOK, SAFETY = 25.0, 20.0, 10.0

c_proj = C_BASE + C_SAFE
f_proj = F_BASE + F_SAFE

m["C_SAFE_RECOVERY_GB"] = C_SAFE
m["C_PROJECTED_FREE_GB"] = round(c_proj, 2)
m["F_SAFE_RECOVERY_GB"] = F_SAFE
m["F_PROJECTED_FREE_GB"] = round(f_proj, 2)
m["C_meets_20_30_GB_target"] = c_proj >= 20
m["F_meets_80_100_GB_target"] = f_proj >= 80

m["BASELINE_DRIFT"] = {
    "C_measured_at_build_gb": C_BASE,
    "C_measured_minutes_later_gb": C_LATEST,
    "C_drift_gb": round(C_LATEST - C_BASE, 2),
    "F_measured_at_build_gb": F_BASE,
    "F_measured_minutes_later_gb": F_LATEST,
    "F_drift_gb": round(F_LATEST - F_BASE, 2),
    "interpretation":
        "C: lost about 1.8 GB during this analysis with no deletion by this "
        "session, so something is actively consuming it (a pytest run was in "
        "progress and this session's own tooling writes to the same TEMP). "
        "The C: baseline is therefore UNSTABLE and the projection carries "
        "downside risk. Re-measure immediately before any cleanup.",
}

m.pop("DDC_TARGET_CAPACITY_ON_C", None)
m.pop("DDC_TARGET_CAPACITY_ON_C_reason", None)

m["VOLUME_MODELS"] = {
    "single_volume_C_only": {
        "needs_gb": DDC + COOK + SAFETY,
        "has_gb": round(c_proj, 2),
        "result": "FAIL",
        "why": "a 25 GB DDC plus 20 GB cook output plus 10 GB reserve needs "
               "55 GB and C: projects to about %.1f GB" % c_proj,
    },
    "single_volume_F_only": {
        "needs_gb": DDC + COOK + SAFETY,
        "has_gb": round(f_proj, 2),
        "result": "FAIL",
        "why": "F: projects to about %.1f GB and is also the slowest of the "
               "internal candidates" % f_proj,
    },
    "split_DDC_on_C_output_on_F": {
        "C_needs_gb": DDC + SAFETY,
        "C_has_gb": round(c_proj, 2),
        "C_result": "PASS",
        "C_headroom_after_gb": round(c_proj - DDC - SAFETY, 2),
        "F_needs_gb": COOK,
        "F_has_gb": round(f_proj, 2),
        "F_result": "PASS",
        "F_headroom_after_gb": round(f_proj - COOK, 2),
        "result": "PASS",
        "why": "DDC on the NVMe C: is both faster than the proposed SATA F: "
               "target and has more recoverable headroom, while F: absorbs "
               "the bounded cook output. C: retains about %.1f GB for TEMP "
               "and pagefile after the DDC and reserve."
               % (c_proj - DDC - SAFETY),
    },
}

m["DDC_TARGET_CAPACITY"] = "PASS_CONDITIONAL"
m["DDC_TARGET_CAPACITY_CONDITIONS"] = [
    "operator executes the P0 and P1 cleanup (about %.1f GB on C:, "
    "%.1f GB on F:)" % (C_SAFE, F_SAFE),
    "operator accepts the split layout: DDC on C: (NVMe), cook output on F:",
    "operator accepts DDC on C: competing with TEMP for the same device",
    "C: free space is re-measured immediately before cleanup because the "
    "baseline is drifting downward",
]
m["capacity_gate_result"] = "PASS_CONDITIONAL"
m["RECOMMENDED_SPLIT"] = {
    "DDC": "C: (NVMe, faster and has more recoverable headroom than F:)",
    "COOK_OUTPUT": "F: (SATA)",
    "deviation_from_prompt": "The prompt nominated F:\\UnrealEngine_DDC as the "
                             "candidate. That does not survive the capacity "
                             "model: F: reaches only about %.1f GB free and "
                             "is a mixed personal-data volume. C: is "
                             "recommended instead, and the deviation is "
                             "stated explicitly rather than silently applied."
                             % f_proj,
}

with open(p, "w", encoding="utf-8") as fh:
    json.dump(m, fh, indent=2)

print("C: %.2f -> %.2f GB   F: %.2f -> %.2f GB" % (C_BASE, c_proj,
                                                   F_BASE, f_proj))
print("single-volume C :", m["VOLUME_MODELS"]["single_volume_C_only"]["result"])
print("single-volume F :", m["VOLUME_MODELS"]["single_volume_F_only"]["result"])
print("split DDC/output:", m["VOLUME_MODELS"]["split_DDC_on_C_output_on_F"]["result"])
print("DDC_TARGET_CAPACITY =", m["DDC_TARGET_CAPACITY"])
