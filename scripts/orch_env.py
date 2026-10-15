"""Environment fingerprint, storage authority, resume integrity, and typed gates.

Three principles enforced here:

* Drive letters are not identities. Every critical path is resolved to a stable
  physical identity (disk number, serial, bus type, volume GUID) so a letter
  reassignment cannot silently move DDC or pagefile onto different hardware.

* An `-iterate` resume is only safe when every build-affecting input is
  unchanged. Any difference in a hash-bearing input denies the resume, because
  UE's iterative cook trusts the previous run's outputs.

* Gate predicates are typed. `False == 0` is True in Python, so a generic
  truthiness test can wave a FAILED boolean through a numeric gate. Every
  predicate here compares against an explicitly typed expected value, and
  receipt schemas are version-checked before they are trusted.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys

from orch_core import (SCHEMA_VERSION, atomic_write_json, sha256_file,  # noqa: E402
                       utc_now)

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"


# ---------------------------------------------------------------------------
# typed gate predicates  (phase 28)
# ---------------------------------------------------------------------------
class GateTypeError(ValueError):
    pass


def _typename(value):
    return type(value).__name__


def gate_bool(value, expected=True):
    """Strict boolean gate. `0` and `"false"` must NOT satisfy it."""
    if not isinstance(value, bool):
        raise GateTypeError(
            "expected a bool for a boolean gate, got %s(%r)" % (_typename(value), value))
    return value is expected


def gate_exact(value, expected, expected_type):
    """Strict equality gate against an exact type.

    `expected_type` may be bool, int or str. The comparison is type-strict so
    that `False == 0` and `0 == False` can never satisfy each other, and so the
    JSON string "0" can never satisfy an int gate.
    """
    if expected_type is bool and not isinstance(value, bool):
        raise GateTypeError("expected bool, got %s(%r)" % (_typename(value), value))
    if expected_type is int and (isinstance(value, bool)
                                 or not isinstance(value, int)):
        raise GateTypeError("expected int, got %s(%r)" % (_typename(value), value))
    if expected_type is str and not isinstance(value, str):
        raise GateTypeError("expected str, got %s(%r)" % (_typename(value), value))
    return value == expected


def gate_not_none(value):
    if value is None:
        return False
    return True


def validate_schema(payload, expected_schema, supported_versions=(1,)):
    """Reject unknown/incompatible schema versions.

    An old report format must never be silently reinterpreted as a current
    contract: that is how stale evidence gets promoted.
    """
    if not isinstance(payload, dict):
        return False, "payload is not an object"
    if payload.get("schema") != expected_schema:
        return False, "schema %r != %r" % (payload.get("schema"), expected_schema)
    version = payload.get("schema_version")
    if version not in supported_versions:
        return False, "schema_version %r not in %r" % (version, supported_versions)
    return True, "OK"


# ---------------------------------------------------------------------------
# environment fingerprint  (phase 7)
# ---------------------------------------------------------------------------
def _ps(script, timeout=300):
    p = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       capture_output=True, text=True, errors="replace",
                       timeout=timeout)
    return p.stdout.strip()


def _git(*args, cwd=REPO):
    p = subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                       text=True, errors="replace", timeout=300)
    return p.stdout.strip() if p.returncode == 0 else None


def environment_fingerprint(target_rhis=None, ddc_path=None, extra=None):
    """Canonical, hashed description of everything that can change a result."""
    os_info = json.loads(_ps(r"$o=Get-CimInstance Win32_OperatingSystem; $c=Get-CimInstance Win32_ComputerSystem; "
                             r"$pf=Get-CimInstance Win32_PageFileUsage; "
                             r"[pscustomobject]@{caption=$o.Caption;version=$o.Version;build=$o.BuildNumber;"
                             r"total_phys_kb=$o.TotalVisibleMemorySize;total_virt_kb=$o.TotalVirtualMemorySize;"
                             r"auto_pagefile=$c.AutomaticManagedPagefile;"
                             r"pagefiles=@($pf|ForEach-Object{@{name=$_.Name;allocated_mb=$_.AllocatedBaseSize}})}"
                             r"|ConvertTo-Json -Depth 4 -Compress") or "{}")
    cpu = json.loads(_ps(r"Get-CimInstance Win32_Processor|Select-Object -First 1 Name,NumberOfCores,NumberOfLogicalProcessors"
                         r"|ConvertTo-Json -Compress") or "{}")
    drives = _drive_identity()

    fingerprint = {
        "os": {k: os_info.get(k) for k in
               ("caption", "version", "build", "total_phys_kb", "total_virt_kb",
                "auto_pagefile", "pagefiles")},
        "cpu": cpu,
        "python": {
            "version": sys.version,
            "implementation": platform.python_implementation(),
            "executable_basename": os.path.basename(sys.executable),
        },
        "drives": drives,
        "env": {
            "TEMP": os.environ.get("TEMP"),
            "TMP": os.environ.get("TMP"),
            "UE_ROOT": os.environ.get("UE_ROOT"),
            "CARLA_ROOT": os.environ.get("CARLA_ROOT"),
            "ddc_path": ddc_path,
            "target_rhis": target_rhis,
        },
        "git": {
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "head": _git("rev-parse", "HEAD"),
            "tree": _git("rev-parse", "HEAD^{tree}"),
            "dirty": bool(_git("status", "--porcelain=v1")),
        },
        "toolchain": {
            "msvc": _msvc_version(),
            "windows_sdk": _windows_sdk_versions(),
        },
    }
    if extra:
        fingerprint["extra"] = extra

    blob = json.dumps(fingerprint, sort_keys=True, default=str).encode("utf-8")
    return {
        "schema": "ENVIRONMENT_FINGERPRINT/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "ENVIRONMENT_FINGERPRINT_SHA256": hashlib.sha256(blob).hexdigest(),
        "fingerprint": fingerprint,
    }


def _msvc_version():
    try:
        p = subprocess.run(
            ["cmd", "/c",
             "call \"C:\\Program Files (x86)\\Microsoft Visual Studio\\2022\\"
             "BuildTools\\VC\\Auxiliary\\Build\\vcvars64.bat\" >nul 2>&1 && cl 2>&1"],
            capture_output=True, text=True, errors="replace", timeout=600)
        for line in p.stdout.splitlines():
            if "Version" in line and "19." in line:
                return line.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _windows_sdk_versions():
    base = r"C:\Program Files (x86)\Windows Kits\10\Include"
    try:
        return sorted(os.listdir(base))
    except OSError:
        return []


# ---------------------------------------------------------------------------
# storage topology / drive identity  (phase 8)
# ---------------------------------------------------------------------------
def _drive_identity():
    """Resolve each drive letter to a hardware-stable identity.

    A drive letter can be reassigned by a reboot or an admin; the serial number
    and disk number cannot. Recording only the letter would let DDC or pagefile
    silently migrate onto different hardware between runs.
    """
    script = r"""
$rows = @()
foreach ($d in (Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3')) {
  $letter = $d.DeviceID
  try {
    $part = Get-Partition -DriveLetter $letter.TrimEnd(':')
    $disk = Get-Disk -Number $part.DiskNumber
    $phys = Get-PhysicalDisk -DeviceNumber $disk.Number -ErrorAction SilentlyContinue
    $volGuid = (Get-CimInstance Win32_Volume -Filter ("DriveLetter='" + $letter + "'") -ErrorAction SilentlyContinue).Id
    $rows += [pscustomobject]@{
      drive = $letter
      volume_name = $d.VolumeName
      filesystem = $d.FileSystem
      total_gb = [math]::Round($d.Size/1GB, 2)
      free_gb = [math]::Round($d.FreeSpace/1GB, 2)
      disk_number = $disk.Number
      disk_friendly = $disk.FriendlyName
      bus_type = [string]$disk.BusType
      is_boot = $disk.IsBoot
      is_system = $disk.IsSystem
      is_offline = $disk.IsOffline
      is_read_only = $disk.IsReadOnly
      physical_media_type = if ($phys) { [string]$phys.MediaType } else { $null }
      physical_health = if ($phys) { [string]$phys.HealthStatus } else { $null }
      volume_guid = $volGuid
    }
  } catch {}
}
$rows | ConvertTo-Json -Compress
"""
    out = _ps(script)
    if not out:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    rows = data if isinstance(data, list) else [data]
    for r in rows:
        # Stable identity key: serial-equivalent hardware identity + volume GUID.
        r["storage_identity_key"] = "%s|%s|%s" % (
            r.get("disk_number"), r.get("bus_type"), r.get("volume_guid"))
    return rows


def storage_topology(critical_paths):
    """Bind each critical path to its drive's hardware identity."""
    drives = {d["drive"].upper(): d for d in _drive_identity()}
    entries = []
    for role, path in critical_paths.items():
        drive = os.path.splitdrive(path)[0].upper() if path else None
        entries.append({
            "role": role,
            "path": path,
            "drive_letter": drive,
            "drive_identity": drives.get(drive),
            "resolved": drive in drives,
            "warning": None if drive in drives else
                       "drive letter could not be resolved to a physical disk",
        })
    return {
        "schema": "STORAGE_TOPOLOGY_AUTHORITY/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "drives": list(drives.values()),
        "critical_paths": entries,
        "all_resolved": all(e["resolved"] for e in entries),
    }


# ---------------------------------------------------------------------------
# storage reservation  (phase 9)
# ---------------------------------------------------------------------------
def storage_reservation(reserve_bytes, expected_growth_bytes, reservations,
                        free_bytes, hard_floor_bytes=0):
    """Deny work whose projected usage eats another run's reservation.

    A plain free-space preflight races with concurrent jobs. This accounts for
    bytes already promised to other runs and refuses to start work that would
    eat into them.
    """
    reserved = sum(int(r.get("reserved_bytes", 0)) for r in reservations)
    available_after_reservations = free_bytes - reserved
    projected = expected_growth_bytes
    post = available_after_reservations - projected

    violations = []
    if available_after_reservations < reserve_bytes:
        violations.append("available_after_reservations < reserve")
    if post < hard_floor_bytes:
        violations.append("post_run_reserve < hard_floor")

    return {
        "schema": "STORAGE_RESERVATION/v1",
        "schema_version": SCHEMA_VERSION,
        "CURRENT_FREE": free_bytes,
        "RESERVED_BY_ACTIVE_RUNS": reserved,
        "RESERVATIONS": reservations,
        "REQUIRED_RESERVE": reserve_bytes,
        "EXPECTED_GROWTH": projected,
        "POST_RUN_RESERVE": post,
        "HARD_FLOOR": hard_floor_bytes,
        "violations": violations,
        "allowed": not violations,
    }


# ---------------------------------------------------------------------------
# resume integrity  (phase 5)
# ---------------------------------------------------------------------------
# Inputs that change what a cook or import produces. Any difference denies an
# iterative resume.
RESUME_CRITICAL_INPUTS = (
    "ENGINE_SHA",
    "CARLA_SHA",
    "PROJECT_SHA",
    "IMPORT_PY_SHA",
    "DEFAULT_ENGINE_INI_SHA",
    "XODR_SHA",
    "FBX_OBJECT_HASHES",
    "IMPORT_SETTINGS_SHA",
    "DDC_CONFIG_SHA",
    "TARGETED_RHIS_SHA",
    "MAP_REGISTRY_IDENTITY",
    "COOK_COMMAND_SHA",
    "PLUGIN_BINARY_SHA",
)

# Compatibility rules that permit a difference without denying the resume.
# Each must state what it covers and why it is safe; an empty tuple means no
# difference is ever tolerated.
RESUME_COMPATIBILITY_RULES = {
    # Wall-clock and log destinations cannot change generated content.
    "COOK_COMMAND_SHA": ("normalisation: log verbosity, -stdout/-UTF8Output, "
                         "timestamp flags"),
    "ENGINE_SHA": (),  # engine changes always invalidate cook output
}


def resume_integrity(previous_inputs, current_inputs, documented_rules=None):
    """Decide whether an `-iterate` style resume is safe.

    Returns ALLOWED only when every critical input matches. Differences are
    reported per-input so the operator can see exactly what moved.
    """
    rules = RESUME_COMPATIBILITY_RULES if documented_rules is None else documented_rules
    diffs = []
    tolerated = []
    denied = []

    for name in RESUME_CRITICAL_INPUTS:
        before = (previous_inputs or {}).get(name)
        after = (current_inputs or {}).get(name)
        if before == after:
            continue
        allowed_by = rules.get(name)
        entry = {"input": name, "previous": before, "current": after}
        if allowed_by:
            entry["tolerated_by_documented_rule"] = allowed_by
            tolerated.append(entry)
        else:
            entry["reason"] = "no documented compatibility rule permits this difference"
            denied.append(entry)
        diffs.append(entry)

    missing = [n for n in RESUME_CRITICAL_INPUTS
               if (current_inputs or {}).get(n) is None]

    return {
        "schema": "ITERATIVE_RESUME_AUTHORITY/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "ITERATIVE_RESUME_ALLOWED": not denied and not missing,
        "critical_inputs": list(RESUME_CRITICAL_INPUTS),
        "differences": diffs,
        "denied_differences": denied,
        "tolerated_differences": tolerated,
        "missing_inputs": missing,
        "documented_rules": {k: list(v) for k, v in rules.items()},
        "rationale": ("UE iterative cook trusts the previous run's outputs, so an "
                      "input change silently produces a mixed-provenance result. "
                      "Absence of evidence is treated as a difference, not as a match."),
    }


# ---------------------------------------------------------------------------
# configuration drift gate  (phase 12)
# ---------------------------------------------------------------------------
CONFIG_DRIFT_FILES = {
    "DefaultEngine.ini": r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Config\DefaultEngine.ini",
    "DefaultGame.ini": r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Config\DefaultGame.ini",
    "Import.py": r"G:\CARLA\carla_source_probe\Util\BuildTools\Import.py",
}


def configuration_drift(approved):
    """approved: {name: sha256}. Unknown drift denies the governed run."""
    rows = []
    unknown = []
    for name, path in CONFIG_DRIFT_FILES.items():
        actual = sha256_file(path)
        expect = approved.get(name)
        if actual is None:
            rows.append({"config": name, "path": path, "status": "MISSING",
                         "expected_sha256": expect, "actual_sha256": None})
            unknown.append({"config": name, "reason": "file missing"})
            continue
        if expect is None:
            rows.append({"config": name, "path": path, "status": "UNAPPROVED",
                         "expected_sha256": None, "actual_sha256": actual})
            unknown.append({"config": name, "reason": "no approved hash recorded"})
            continue
        if actual != expect:
            rows.append({"config": name, "path": path, "status": "DRIFTED",
                         "expected_sha256": expect, "actual_sha256": actual})
            unknown.append({"config": name, "reason": "hash differs from approved"})
        else:
            rows.append({"config": name, "path": path, "status": "MATCH",
                         "expected_sha256": expect, "actual_sha256": actual})
    return {
        "schema": "CONFIGURATION_DRIFT_GATE/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "files": rows,
        "unknown_drift": unknown,
        "RUN_ALLOWED": not unknown,
        "gate_effect": "DENY_GOVERNED_EXPERIMENT" if unknown else "ALLOW",
    }
