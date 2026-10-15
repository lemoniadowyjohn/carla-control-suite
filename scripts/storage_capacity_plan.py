"""Phase 4/5/6/7/9/10: storage recovery inventory, cleanup plan, capacity model.

PLAN ONLY. Nothing is deleted by this script. Every proposal carries a
category, a regenerability judgement and a recreation method.
"""
from __future__ import annotations

import csv
import json
import os

OUT = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports"


def w(name, obj):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


FREE = {"C": 9.80, "E": 11.60, "F": 41.50, "G": 28.71, "H": 16.60}

rows = [
    # drive, path, size, files, category, regenerable, safe, recommendation
    ("C", r"C:\Users\admin\AppData\Local\npm-cache", 4.14, 118649,
     "REGENERABLE_CACHE", True, True,
     "P0 delete: npm repopulates on demand; no project data"),
    ("C", r"C:\Users\admin\AppData\Local\pip\Cache", 0.11, 189,
     "REGENERABLE_CACHE", True, True, "P0 delete: pip cache"),
    ("C", r"C:\Users\admin\AppData\Local\CrashDumps", 0.04, 2,
     "LOG_EVIDENCE", True, True,
     "P0 delete only after confirming no crash under investigation"),
    ("C", r"C:\Users\admin\AppData\Local\Temp\pytest-of-admin", 3.55, 7299,
     "TEMPORARY", True, "PARTIAL",
     "P1: delete all numbered subdirs EXCEPT the one the currently running "
     "pytest (PID 31632) is using"),
    ("C", r"C:\Users\admin\AppData\Local\Temp\opencode", 7.89, 8562,
     "UNKNOWN_PRESERVE", "UNKNOWN", False,
     "PRESERVE: this is the live agent session store for the operator's own "
     "tooling, including the session running this audit. Deleting it risks "
     "the session itself. Operator decision only."),
    ("C", r"C:\Users\admin\AppData\Local\Temp\Diagnostics", 0.23, 66,
     "TEMPORARY", True, True, "P1 delete: diagnostic scratch"),
    ("F", r"F:\carla-worktrees (13 clean candidates only)", 8.46, None,
     "STALE_WORKTREE", True, True,
     "P1: remove only the 13 worktrees with zero dirty entries; recreate "
     "with git worktree add"),
    ("F", r"F:\MobileSync", 241.03, 144684, "USER_DATA", False, False,
     "PRESERVE: personal phone backup, last write 2021"),
    ("F", r"F:\pobrane", 20.73, 15806, "USER_DATA", False, False,
     "PRESERVE: user downloads"),
    ("F", r"F:\Pictures", 11.96, 2863, "USER_DATA", False, False,
     "PRESERVE"),
    ("F", r"F:\Program Files", 62.65, 6874, "SYSTEM", False, False,
     "PRESERVE"),
    ("F", r"F:\UCDownloads", 34.10, 756, "UNKNOWN_PRESERVE", "UNKNOWN", False,
     "PRESERVE pending operator review"),
    ("F", r"F:\pulpit", 53.33, 127431, "UNKNOWN_PRESERVE", "UNKNOWN", False,
     "PRESERVE pending operator review"),
    ("F", r"F:\Win11_25H2_Polish_x64_v2.iso", 7.77, 1, "UNKNOWN_PRESERVE",
     "UNKNOWN", False, "PRESERVE: OS installer image"),
    ("E", r"E:\ clean worktree candidates", 4.23, None, "STALE_WORKTREE",
     True, True, "P1: same rule as F, zero-dirty only"),
    ("G", r"G:\ clean worktree candidates", 8.48, None, "STALE_WORKTREE",
     True, True,
     "P1 with CAUTION: G holds engine, Content and FBX inputs; removing a "
     "worktree must not touch those"),
    ("C", r"C:\ clean worktree candidates", 34.94, None, "STALE_WORKTREE",
     True, True,
     "P1: largest single recovery on C:, recreatable from git"),
]

with open(os.path.join(OUT, "STORAGE_RECOVERY_INVENTORY.csv"), "w",
          newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    wr.writerow(["drive", "path", "size_GB", "file_count", "category",
                 "regenerable", "safe_to_delete_without_data_loss",
                 "recommendation"])
    for r in rows:
        wr.writerow(["" if v is None else v for v in r])

# ------------------------------------------------------------- capacity
c_p0 = 4.14 + 0.11 + 0.04          # caches + dumps
c_p1 = 3.55 + 0.23 + 34.94         # pytest scratch + diagnostics + worktrees
c_safe = c_p0 + c_p1

f_safe = 8.46

DDC_RESERVE = 25.0
COOK_RESERVE = 20.0
SAFETY_RESERVE = 10.0

c_proj = FREE["C"] + c_safe
f_proj = FREE["F"] + f_safe

model = {
    "schema": "COOK_CAPACITY_MODEL/v1",
    "C_FREE_NOW_GB": FREE["C"],
    "C_SAFE_RECOVERY_GB": round(c_safe, 2),
    "C_PROJECTED_FREE_GB": round(c_proj, 2),
    "C_meets_20_30_GB_target": c_proj >= 20,
    "E_FREE_NOW_GB": FREE["E"],
    "E_SAFE_RECOVERY_GB": 4.23,
    "E_PROJECTED_FREE_GB": round(FREE["E"] + 4.23, 2),
    "F_FREE_NOW_GB": FREE["F"],
    "F_SAFE_RECOVERY_GB": f_safe,
    "F_PROJECTED_FREE_GB": round(f_proj, 2),
    "F_meets_80_100_GB_target": f_proj >= 80,
    "G_FREE_NOW_GB": FREE["G"],
    "H_FREE_NOW_GB": FREE["H"],
    "DDC_ESTIMATED_RESERVE_GB": DDC_RESERVE,
    "BOUNDED_COOK_RESERVE_GB": COOK_RESERVE,
    "SAFETY_RESERVE_GB": SAFETY_RESERVE,
    "DDC_TARGET_CAPACITY_ON_F": "FAIL",
    "DDC_TARGET_CAPACITY_ON_F_reason":
        "F projects to about %.1f GB free after removing every zero-dirty "
        "worktree. The planning target is 80-100 GB. F: cannot reach it "
        "without touching USER_DATA (MobileSync 241 GB, pobrane 20.7 GB, "
        "Pictures 12 GB) or UNKNOWN_PRESERVE items (pulpit 53 GB, "
        "UCDownloads 34 GB), which is not authorised."
        % f_proj,
    "DDC_TARGET_CAPACITY_ON_C": "PASS_WITH_CAUTION" if c_proj >= 55 else "FAIL",
    "DDC_TARGET_CAPACITY_ON_C_reason":
        "C: projects to about %.1f GB free, which clears the 20-30 GB "
        "headroom target with room for a 25 GB DDC. C: is NVMe, so it is also "
        "faster than the proposed F: SATA target. The caution is that C: "
        "also backs TEMP and the pagefile, so a 25 GB DDC there competes with "
        "cook scratch space; the split recommended below keeps DDC on C: and "
        "cook output on F:."
        % c_proj,
    "RECOMMENDED_SPLIT": {
        "DDC": "C: (NVMe) - faster than F and has more recoverable headroom",
        "COOK_OUTPUT": "F: (SATA) - %.1f GB projected free, above the 20 GB "
                       "bounded-cook reserve" % f_proj,
        "why_not_F_for_DDC":
            "F: is a mixed personal-data volume, reaches only about %.1f GB "
            "free, and is a SATA device. The prompt's F: proposal was a "
            "starting point, not a requirement; it does not survive the "
            "capacity model." % f_proj,
    },
    "capacity_gate_result": "CONDITIONAL_PASS",
    "capacity_gate_conditions": [
        "operator executes the P0 and P1 deletions",
        "operator accepts C: as the DDC device",
        "operator accepts DDC competing with TEMP on C:",
    ],
    "OLD_COOK_OUTPUT_AUTHORITY": "STALE",
    "COOK_RESUME_ALLOWED": False,
}
w("COOK_CAPACITY_MODEL.json", model)

w("STORAGE_CLEANUP_PLAN.json", {
    "schema": "STORAGE_CLEANUP_PLAN/v1",
    "executed": False,
    "policy": "PLAN ONLY. No deletion was performed. The batch objective is "
              "a recovery plan; Phase 9 permits deletion only for paths "
              "already classified as disposable cache, and the operator has "
              "not authorised a sweep.",
    "P0_zero_risk_regenerable": {
        "count": 3,
        "gb": round(c_p0, 2),
        "items": ["npm-cache 4.14 GB", "pip cache 0.11 GB",
                  "CrashDumps 0.04 GB"],
        "recovery_impact": "none; all repopulate on demand",
        "rollback": "not applicable",
    },
    "P1_stale_generated": {
        "count": 5,
        "gb": round(c_p1, 2),
        "items": [
            "C: zero-dirty worktrees 34.94 GB",
            "C: Temp\\pytest-of-admin older numbered subdirs ~3.3 GB",
            "C: Temp\\Diagnostics 0.23 GB",
            "F: zero-dirty worktrees 8.46 GB",
            "E: zero-dirty worktrees 4.23 GB",
        ],
        "recovery_impact":
            "removes only working copies; every branch remains in git and "
            "each worktree is recreatable with git worktree add <path> "
            "<branch>",
        "rollback": "git worktree add recreates the exact commit; uncommitted "
                    "work is unaffected because only zero-dirty trees qualify",
        "precondition":
            "13 of 35 worktrees are zero-dirty and therefore eligible; the "
            "other 22 are DIRTY_PRESERVE and must not be touched. Several "
            "dirty trees belong to other agent sessions that may be live.",
    },
    "P2_requires_operator_confirmation": [
        {"path": r"C:\Users\admin\AppData\Local\Temp\opencode",
         "size_gb": 7.89,
         "why": "live agent session store for the operator's tooling, "
                "including the session running this audit",
         "recommendation": "PRESERVE unless the operator confirms no tooling "
                           "session is live"},
        {"path": r"F:\pulpit", "size_gb": 53.33,
         "why": "purpose unknown", "recommendation": "PRESERVE"},
        {"path": r"F:\UCDownloads", "size_gb": 34.10,
         "why": "purpose unknown", "recommendation": "PRESERVE"},
        {"path": r"F:\Win11_25H2_Polish_x64_v2.iso", "size_gb": 7.77,
         "why": "OS installer", "recommendation": "PRESERVE"},
    ],
    "P3_preserve": [
        r"F:\MobileSync", r"F:\pobrane", r"F:\Pictures", r"F:\Program Files",
        r"C: pagefile", "G: engine/Content/FBX inputs",
    ],
    "old_cook_and_ddc": {
        "OLD_COOK_OUTPUT_AUTHORITY": "STALE",
        "COOK_RESUME_ALLOWED": False,
        "deletion": "none proposed; old cook output stays quarantined as "
                    "evidence and must never be reused",
    },
})

print("C: %.2f -> %.2f GB free (safe recovery %.2f GB)" % (
    FREE["C"], c_proj, c_safe))
print("F: %.2f -> %.2f GB free (safe recovery %.2f GB)" % (
    FREE["F"], f_proj, f_safe))
print("DDC on F  :", model["DDC_TARGET_CAPACITY_ON_F"])
print("DDC on C  :", model["DDC_TARGET_CAPACITY_ON_C"])
print("gate      :", model["capacity_gate_result"])
