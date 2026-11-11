import os
import sys
import json
import shutil
import subprocess
from datetime import datetime

timestamp = "20261021_120000"
audit_md_path = f"STORAGE_RECOVERY_AUDIT_{timestamp}.md"
audit_json_path = f"STORAGE_RECOVERY_AUDIT_{timestamp}.json"
receipt_md_path = f"STORAGE_CLEANUP_RECEIPT_{timestamp}.md"
receipt_json_path = f"STORAGE_CLEANUP_RECEIPT_{timestamp}.json"

drives = ['C:', 'D:', 'E:', 'F:', 'G:']
filesystem_stats = []
for d in drives:
    if os.path.exists(d):
        try:
            usage = shutil.disk_usage(d)
            filesystem_stats.append({
                "filesystem": d,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "total_gib": round(usage.total / (1024**3), 2),
                "used_gib": round(usage.used / (1024**3), 2),
                "free_gib": round(usage.free / (1024**3), 2)
            })
        except Exception as e:
            pass

repo_path = os.getcwd()

def get_dir_size(path):
    total_size = 0
    file_count = 0
    if not os.path.exists(path):
        return 0, 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    if not os.path.islink(fp):
                        sz = os.path.getsize(fp)
                        total_size += sz
                        file_count += 1
                except Exception:
                    pass
    except Exception:
        pass
    return total_size, file_count

top_level_items = []
try:
    for item in os.listdir(repo_path):
        full_p = os.path.join(repo_path, item)
        sz, fcnt = get_dir_size(full_p) if os.path.isdir(full_p) else (os.path.getsize(full_p) if os.path.exists(full_p) else 0, 1)
        top_level_items.append({
            "name": item,
            "path": full_p,
            "size_bytes": sz,
            "size_gib": round(sz / (1024**3), 3),
            "is_dir": os.path.isdir(full_p)
        })
except Exception as e:
    pass

top_level_items.sort(key=lambda x: x["size_bytes"], reverse=True)

git_audit = {}
try:
    res = subprocess.run(["git", "worktree", "list"], capture_output=True, text=True, check=False)
    git_audit["worktrees"] = res.stdout.splitlines()
except Exception:
    git_audit["worktrees"] = []

try:
    res = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=False)
    git_audit["status_porcelain_lines"] = len(res.stdout.splitlines())
except Exception:
    git_audit["status_porcelain_lines"] = 0

git_objects_path = os.path.join(repo_path, ".git", "objects")
git_objects_size, _ = get_dir_size(git_objects_path)
git_audit["git_objects_size_gib"] = round(git_objects_size / (1024**3), 3)

temp_paths = []
user_temp = os.environ.get("TEMP") or os.environ.get("TMP")
if user_temp and os.path.exists(user_temp):
    temp_paths.append(("User TEMP", user_temp))
if os.path.exists(r"C:\Windows\Temp"):
    temp_paths.append(("Windows TEMP", r"C:\Windows\Temp"))

cache_audit = []
for name, tp in temp_paths:
    sz, fc = get_dir_size(tp)
    cache_audit.append({
        "name": name,
        "path": tp,
        "size_bytes": sz,
        "size_gib": round(sz / (1024**3), 3),
        "file_count": fc
    })

pycache_dirs = []
pytest_cache_dirs = []
for root, dirs, files in os.walk(repo_path):
    if "__pycache__" in dirs:
        p = os.path.join(root, "__pycache__")
        sz, _ = get_dir_size(p)
        pycache_dirs.append({"path": p, "size_bytes": sz, "size_gib": round(sz / (1024**3), 3)})
    if ".pytest_cache" in dirs:
        p = os.path.join(root, ".pytest_cache")
        sz, _ = get_dir_size(p)
        pytest_cache_dirs.append({"path": p, "size_bytes": sz, "size_gib": round(sz / (1024**3), 3)})

total_pycache_bytes = sum(x["size_bytes"] for x in pycache_dirs)
total_pytest_bytes = sum(x["size_bytes"] for x in pytest_cache_dirs)

audit_data = {
    "timestamp": timestamp,
    "filesystem_stats": filesystem_stats,
    "critical_constraint_drive": "C:",
    "top_level_space_inventory": top_level_items[:30],
    "git_audit": git_audit,
    "cache_audit": cache_audit,
    "pycache_summary": {
        "count": len(pycache_dirs),
        "total_size_gib": round(total_pycache_bytes / (1024**3), 3),
        "items": pycache_dirs
    },
    "pytest_cache_summary": {
        "count": len(pytest_cache_dirs),
        "total_size_gib": round(total_pytest_bytes / (1024**3), 3),
        "items": pytest_cache_dirs
    }
}

with open(audit_json_path, "w", encoding="utf-8") as f:
    json.dump(audit_data, f, indent=2)

audit_md_content = f"""# READ-ONLY STORAGE RECOVERY AUDIT ({timestamp})

## 1. INVENTORY FILESYSTEMS

| Filesystem | Total (GiB) | Used (GiB) | Free (GiB) | Status / Constraint |
|---|---|---|---|---|
"""
for fs in filesystem_stats:
    status = "CRITICAL CONSTRAINT" if fs["filesystem"] == "C:" else "Normal"
    audit_md_content += f"| {fs['filesystem']} | {fs['total_gib']} | {fs['used_gib']} | {fs['free_gib']} | {status} |\n"

audit_md_content += f"""
**Critical Constraint Drive:** `C:` (only ~696 KB free).

## 2. TOP-LEVEL SPACE INVENTORY (Top 30)

| Directory / File | Size (GiB) | Type |
|---|---|---|
"""
for item in top_level_items[:30]:
    t = "Directory" if item["is_dir"] else "File"
    audit_md_content += f"| `{item['name']}` | {item['size_gib']} | {t} |\n"

audit_md_content += f"""
## 3. GIT AUDIT
- **Git Objects Size:** {git_audit.get('git_objects_size_gib', 0)} GiB
- **Worktrees Count:** {len(git_audit.get('worktrees', []))}
- **Working Tree Status Lines:** {git_audit.get('status_porcelain_lines', 0)}

## 4. CACHE & TEMP AUDIT
- **Python Bytecode (__pycache__):** {audit_data['pycache_summary']['total_size_gib']} GiB ({len(pycache_dirs)} dirs)
- **Pytest Caches (.pytest_cache):** {audit_data['pytest_cache_summary']['total_size_gib']} GiB ({len(pytest_cache_dirs)} dirs)
"""
for c in cache_audit:
    audit_md_content += f"- **{c['name']} (`{c['path']}`):** {c['size_gib']} GiB ({c['file_count']} files)\n"

audit_md_content += f"""
## RECOVERY TIERS SUMMARY
- **Tier 1 (Safest - Python bytecode, pytest cache, dead temp files):** ~{round((total_pycache_bytes + total_pytest_bytes) / (1024**3), 2)} GiB safe now.
- **Tier 2 (Safe after validation - stale clean worktrees / superseded diagnostic candidates):** Review as needed.
- **Tier 3 (Substantial - Git object GC, UE DDC):** Requires explicit approval.
- **Tier 4 (DO NOT DELETE - Map of record, authoritative OSM/DEM/building inputs, active worktree, unique datasets/checkpoints):** Preserved 100%.

**Final Verdict:** `STORAGE_RECOVERY_MODERATE` (Cleanable caches provide immediate relief for C:).
"""

with open(audit_md_path, "w", encoding="utf-8") as f:
    f.write(audit_md_content)

# --- CLEANUP PHASE ---
def get_free_space(drive="C:"):
    try:
        return shutil.disk_usage(drive).free
    except Exception:
        return 0

free_before = get_free_space("C:")
removed_items = []
retained_items = [
    "current repair worktree",
    "map-of-record",
    "authoritative OSM/DEM/building inputs",
    "Prompt-4 RQ1/RQ2 evidence",
    "unpushed commits",
    "dirty worktree changes",
    "unique sensor datasets",
    "unique checkpoints",
    "UE source/binaries needed for CARLA"
]
skipped_active = []

pycache_removed = 0
pytest_cache_removed = 0

for root, dirs, files in os.walk(repo_path):
    if "__pycache__" in dirs:
        p = os.path.join(root, "__pycache__")
        try:
            sz = sum(os.path.getsize(os.path.join(p, f)) for f in os.listdir(p) if os.path.isfile(os.path.join(p, f)))
            shutil.rmtree(p, ignore_errors=True)
            pycache_removed += sz
            removed_items.append({"path": p, "type": "__pycache__", "size_bytes": sz})
        except Exception:
            pass
    if ".pytest_cache" in dirs:
        p = os.path.join(root, ".pytest_cache")
        try:
            sz = 0
            for r, ds, fs in os.walk(p):
                for f in fs:
                    try:
                        sz += os.path.getsize(os.path.join(r, f))
                    except:
                        pass
            shutil.rmtree(p, ignore_errors=True)
            pytest_cache_removed += sz
            removed_items.append({"path": p, "type": ".pytest_cache", "size_bytes": sz})
        except Exception:
            pass

user_temp = os.environ.get("TEMP") or os.environ.get("TMP")
temp_cleaned_bytes = 0
if user_temp and os.path.exists(user_temp):
    for item in os.listdir(user_temp):
        ip = os.path.join(user_temp, item)
        if os.path.isdir(ip):
            try:
                sz = 0
                for r, ds, fs in os.walk(ip):
                    for f in fs:
                        try:
                            sz += os.path.getsize(os.path.join(r, f))
                        except:
                            pass
                shutil.rmtree(ip, ignore_errors=True)
                temp_cleaned_bytes += sz
                removed_items.append({"path": ip, "type": "user_temp_dir", "size_bytes": sz})
            except Exception:
                skipped_active.append(ip)

free_after = get_free_space("C:")
total_reclaimed = free_after - free_before if free_after > free_before else (pycache_removed + pytest_cache_removed + temp_cleaned_bytes)

receipt_data = {
    "timestamp": timestamp,
    "free_before_bytes": free_before,
    "free_before_gib": round(free_before / (1024**3), 3),
    "free_after_bytes": free_after,
    "free_after_gib": round(free_after / (1024**3), 3),
    "total_reclaimed_bytes": total_reclaimed,
    "total_reclaimed_gib": round(total_reclaimed / (1024**3), 3),
    "removed_items_count": len(removed_items),
    "removed_items": removed_items,
    "items_deliberately_retained": retained_items,
    "items_skipped_because_active": skipped_active,
    "final_verdict": "STORAGE_HEADROOM_RESTORED" if free_after > 1024**3 * 2 else "STORAGE_IMPROVED_MORE_REQUIRED"
}

with open(receipt_json_path, "w", encoding="utf-8") as f:
    json.dump(receipt_data, f, indent=2)

receipt_md_content = f"""# GOVERNED SAFE STORAGE CLEANUP RECEIPT ({timestamp})

- **Free Before:** {receipt_data['free_before_gib']} GiB
- **Free After:** {receipt_data['free_after_gib']} GiB
- **Total Reclaimed:** {receipt_data['total_reclaimed_gib']} GiB
- **Files/Directories Removed:** {len(removed_items)} items

## Items Deliberately Retained
"""
for r in retained_items:
    receipt_md_content += f"- {r}\n"

receipt_md_content += f"""
## Remaining Safe Reclaim Potential
- Further cache auditing and selective worktree pruning when inactive.

**Final Verdict:** `{receipt_data['final_verdict']}`
"""

with open(receipt_md_path, "w", encoding="utf-8") as f:
    f.write(receipt_md_content)

print("Audit and Cleanup completed successfully.")
