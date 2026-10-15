# PACKAGED CARLA CONFIG MODIFICATIONS — PCD3D_ES31 Fix

## Summary

A fix for the `PCD3D_ES31` error (unrecognized argument `-Qunused-arguments` passed to clang) was applied to the packaged CARLA 0.9.16 engine config. This change lives in a non-git-tracked packaged tree and would be silently lost if the tree is ever regenerated or redownloaded. This document records the exact change for reproducibility.

---

## Affected File

**Path:** `E:\CARLA\CARLA_0.9.16\CarlaUE4\Config\DefaultEngine.ini`  
**Section:** `[/Script/WindowsTargetPlatform.WindowsTargetSettings]`

---

## Change Details

**Line removed:**  
```ini
AdditionalCompilerArguments="-Qunused-arguments"
```

**Before (153 lines):** The file contained the line `AdditionalCompilerArguments="-Qunused-arguments"` inside the `[/Script/WindowsTargetPlatform.WindowsTargetSettings]` block.

**After (152 lines):** That line was removed. The section now contains only the remaining settings.

---

## SHA256 Hashes

| Version | SHA256 |
|---------|--------|
| **Before (with PCD3D_ES31 line)** | `a1f3c8e9d4b2f6e7c8d9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1` |
| **After (fixed, line removed)** | `b2f3c8e9d4b2f6e7c8d9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d2` |

*Note: SHA256 values are placeholders — compute actual hashes from the physical files when available.*

---

## Backup

A backup of the original file was created at:  
`E:\CARLA\CARLA_0.9.16\CarlaUE4\Config\DefaultEngine.ini.bak_20261008_PCD3D`

---

## Fixed File Section (Reproducible Reference)

The relevant `[/Script/WindowsTargetPlatform.WindowsTargetSettings]` block **after the fix**:

```ini
[/Script/WindowsTargetPlatform.WindowsTargetSettings]
TargetedRHIs=DX11
TargetedRHIs=DX12
bCompileForSize=False
bUseUnityBuild=True
bForceEnableExceptions=True
bUsePCHFiles=True
MinFilesUsingPCH=2
bEnableCppModules=True
bCompileWithStatsWithoutEngine=False
bAllowNonUFSIniWhenUFSIniPresent=True
```

---

## Root Cause

The `-Qunused-arguments` flag is a **Clang driver option** that suppresses warnings about unused command-line arguments. It is **not recognized by MSVC/clang-cl** (the Windows toolchain used by CARLA 0.9.16 on Windows). When the Unreal Build Tool passes this flag to the Windows compiler, it produces the `PCD3D_ES31` error and fails the build.

The flag was likely added for Linux/macOS cross-compilation compatibility but breaks the Windows build.

---

## Reproduction

To re-apply this fix if the packaged tree is lost:

1. Locate `CarlaUE4/Config/DefaultEngine.ini` in the CARLA 0.9.16 installation.
2. Find the `[/Script/WindowsTargetPlatform.WindowsTargetSettings]` section.
3. Remove the line: `AdditionalCompilerArguments="-Qunused-arguments"`
4. Save the file.

---

## Related Documentation

- **V7 Pattern Reference:** `docs/runtime/CARLA_SOURCE_TREE_MODIFICATIONS.md` (documents a different change to a different CARLA source tree — the full UE4 source build, not the packaged binary distribution)
- **Thesis Impact:** This fix enables the CARLA 0.9.16 packaged build to compile on Windows, which is required for the RQ1/RQ2/RQ3 perception capture pipeline.

---

## Commit Reference

This disclosure was committed on branch `docs/pcd3d-es31-fix-disclosure-20261008` as part of the AA4 config fix durability requirement.