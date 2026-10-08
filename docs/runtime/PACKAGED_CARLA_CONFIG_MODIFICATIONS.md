# PACKAGED CARLA CONFIG MODIFICATIONS

Durability record for configuration changes made to the **packaged** CARLA tree,
which is **not** under git. If that tree is regenerated or re-downloaded, the
changes below are silently lost with nothing to restore them from. This document
is the restoration source.

Follows the V7 pattern of `docs/runtime/CARLA_SOURCE_TREE_MODIFICATIONS.md`, which
records a different change to a different CARLA tree (the full UE4 *source* build
on `G:`, which IS a git repo). This file covers the *packaged* tree on `E:`.

---

## Modification 1 — remove `+TargetedRHIs=PCD3D_ES31` (2026-10-08)

**Applies to**: GAP-049 (cook stall contributing factor). AA4 applied this;
this section makes it reproducible.

### Affected file

| | |
|---|---|
| Path | `E:\CARLA\CARLA_0.9.16\CarlaUE4\Config\DefaultEngine.ini` |
| Section | `[/Script/WindowsTargetPlatform.WindowsTargetSettings]` |
| Git-tracked | **No.** `E:\CARLA\CARLA_0.9.16` is not a git repository. |
| Backup | `E:\CARLA\CARLA_0.9.16\CarlaUE4\Config\DefaultEngine.ini.bak_20261008_PCD3D` |

### Exact line removed

```ini
+TargetedRHIs=PCD3D_ES31
```

One line. Verified by `Compare-Object` against the backup — the *only*
difference between before and after is this single line.

### Line counts and SHA256 (computed from the physical files, not placeholders)

| Version | Lines | SHA256 |
|---|---|---|
| **Before** (the `.bak_20261008_PCD3D` backup) | 153 | `7531c573494d0c4639f23ba98efdb0e17b35752996cd31fda117fc1e7142e4b0` |
| **After** (current file) | 152 | `dcd2ccf1e146dc5f5c10ce368ff624bab03c76556a2a244730f8a35e98f56a05` |

Both hashes were produced with `Get-FileHash -Algorithm SHA256` against the real
files and are reproducible by re-running that command.

### The section after the fix (verbatim, lines 104–120)

```ini
[/Script/WindowsTargetPlatform.WindowsTargetSettings]
Compiler=Default
-TargetedRHIs=PCD3D_SM5
+TargetedRHIs=PCD3D_SM5
+TargetedRHIs=SF_VULKAN_SM5
DefaultGraphicsRHI=DefaultGraphicsRHI_DX12
MinimumOSVersion=MSOS_Vista
bTarget32Bit=False
AudioSampleRate=48000
AudioCallbackBufferFrameSize=1024
AudioNumBuffersToEnqueue=1
AudioNumChannels=0
AudioNumSourceWorkers=4
SpatializationPlugin=
ReverbPlugin=
OcclusionPlugin=
CompressionOverrides=(bOverrideCompressionTimes=False,DurationThreshold=5.000000,MaxNumRandomBranches=0,SoundCueQualityIndex=0)
```

The effective `+TargetedRHIs` set after the change is exactly
`[PCD3D_SM5, SF_VULKAN_SM5]`, which is what
`reports/production_readiness/root_level_artifacts_20261007/SHADER_PLATFORM_SCOPE_AUDIT.json`
declares as the expected platform set (`PCD3D_ES31_REQUIRED: false`).

### Why

`PCD3D_ES31` is the OpenGL ES 3.1 shader platform — mobile/embedded. The
WindowsNoEditor desktop target requires only `PCD3D_SM5` and `SF_VULKAN_SM5`.
Its presence added roughly a third more shader permutations per material and is
implicated in the package-2975 cook stall: 49 of 49 `for platform …` mentions in
the stalled session were `PCD3D_ES31`, and all 38 `MSM_Hair not supported in
feature level ES3_1` material failures are ES3.1-only.

### Where this is NOT

`G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Config\DefaultEngine.ini` (the UE4
**source** tree, which IS a git repo) never contained this line and was **not**
modified. A machine-wide scan of all five `DefaultEngine.ini` files found the
line in exactly one place — the packaged tree above. Note that
`G:\UnrealEngine_4.26_CARLA\Unreal\CarlaUE4\Config\DefaultEngine.ini`, the path
named in GAP-049's original description, does not exist on this machine; that
register entry was corrected separately.

### Deliberately not modified

`G:\CARLA\cook_out\Ingolstadt\CarlaUE4\Metadata\CookedIniVersion.txt` also
references `PCD3D_ES31`. It is a **cooked output artifact** recording the config
as consumed by the previous cook, so it is the historical record of the failing
run and must not be rewritten. It will change only when a new cook is
deliberately launched.

### Status: applied, NOT validated by a cook

No cook was run to validate this. Its effect on the stall is a hypothesis
consistent with the shader-scope evidence, **not** a measured outcome. Cook
attempts have previously taken up to 14+ hours and hung, OOM'd or stalled, so
re-cooking remains a separate deliberate decision.

### Receipt

`carla-control-plane/reports/control_plane/PCD3D_ES31_CONFIG_FIX_20261008.json`
records the before/after, the confirmation that no build or cook process was
started, and the `PCD3D_ES31` reference inventory.

---

## Restoration procedure

If `E:\CARLA\CARLA_0.9.16` is regenerated or re-downloaded:

1. Locate `CarlaUE4\Config\DefaultEngine.ini` in the new packaged tree.
2. Confirm `[/Script/WindowsTargetPlatform.WindowsTargetSettings]` contains
   `+TargetedRHIs=PCD3D_ES31` (i.e. the modification was lost).
3. Delete that one line. Do not alter any other entry.
4. Verify the resulting file has **152** lines and SHA256
   `dcd2ccf1e146dc5f5c10ce368ff624bab03c76556a2a244730f8a35e98f56a05`.
   A mismatch means the packaged tree differs from the one this was applied to;
   re-derive rather than force the hash.
5. If the backup `.bak_20261008_PCD3D` still exists, it is the authoritative
   153-line "before" (SHA256 `7531c573…`); copy it over the file and redo step 3.

## Verification commands

```powershell
$p = "E:\CARLA\CARLA_0.9.16\CarlaUE4\Config\DefaultEngine.ini"
Get-FileHash $p -Algorithm SHA256
(Get-Content $p).Count                                  # expect 152
Select-String -Path $p -Pattern "PCD3D_ES31"            # expect no matches
Select-String -Path $p -Pattern "TargetedRHIs"          # expect SM5 + SF_VULKAN_SM5 only
Compare-Object (Get-Content "$p.bak_20261008_PCD3D") (Get-Content $p)
```