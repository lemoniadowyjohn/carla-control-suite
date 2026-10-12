# GAP-049 Cook Write-Failure Analysis (2026-10-11 run)

## Terminal result

- `CURRENT_COOK_RESULT=FAIL`, `CURRENT_FAILURE_CLASS=SAVE_PACKAGE_WRITE_FAILURE`
- Historical "silent hang" analysis is `SUPERSEDED_FOR_THIS_RUN` (explicit fatal present).
- Progress at death: 3159/3558 packages (88.8%). Last diagnostics: OpenFileHandles=3559, VirtualMemory=6474MiB.
- Verbatim terminal (cook_20261011_125615.log:623-627):
  `Runnable thread TaskGraphThreadNP 2 crashed` → `SavePackageUtilities.cpp [Line: 527]` →
  `Could not write to G:/CARLA/cook_out/Ingolstadt/.../MH_microdetail/T_Fabric_15_R.ubulk!`

## Write-path mechanism (proven at engine source)

`G:/UnrealEngine_4.26_CARLA/.../SavePackageUtilities.cpp:527` is the `else`
branch of `WriteToFile`: `IFileManager::CreateFileWriter(*Filename)` returned
nullptr, i.e. the target file could not even be OPENED (a short write would
hit line 522 "Could not save to" instead). Callchain:
`AsyncWriteFile → WriteToFile → CreateFileWriter(Filename)` writes DIRECTLY to
the G: target (`SAVEPACKAGE_LINE527_WRITE_CLASS=DIRECT_G`; no temp-then-rename
in this path).

## Falsified causes

- Path length 114 chars (no MAX_PATH), target directory exists, sibling
  `T_Fabric_15_*` artifacts cooked minutes earlier.
- G: volume healthy with 52.87 GB free (no disk-full on target).
- No `Ran out of memory` in log; commit charge modest (census peak 1.52%).
- Windows System log 12:50-14:00: NO Ntfs/storahci/Kernel-PnP/WHEA/Application-Error
  events; recurrent `disk` ID 154 LBA-0x0 hardware errors reference a phantom
  "Disk 3" matching none of the C/F/G/E volumes (G=Disk2, C=Disk1, E/F=Disk0)
  — unattributed noise, not G: evidence.
- C: volume filled 9.30 → ~0 GB during the window (cook scratch/DDC/poller
  pressure); the poller itself died ENOSPC after writing 273 MB of 99.4%-noise
  CSV. C: pressure is real but does not explain a G:-target create failure.

## Remaining hypotheses (unresolved, in priority order)

1. Transient file lock (AV/indexer) on the `.ubulk` create path.
2. Handle-table pressure (3559 open file handles at death).
3. Filesystem/driver transient on G: with no Event-Log trace.

## What this evidence supports

- Terminal classification `SAVE_PACKAGE_WRITE_FAILURE` (new classifier +
  regression fixture in `tools/cook_diagnostics/cook_terminal_classifier.py`).
- Next cook requires: G: write qualification PASS, effective DDC/TEMP proof,
  C: >= 20 GB headroom, hardened poller, no concurrent mutators.
