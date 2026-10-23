# Storage and native toolchain admission audit
- Deliverable: `CARLA_STORAGE_AND_NATIVE_BUILD_ADMISSION.md`
- Verdict: STORAGE_TIGHT_NOT_UNSAFE; NATIVE_BUILD_NOT_ADMITTED (not executed)
- Storage: C 9.9 GB, D 1.2 GB, E 4.2 GB, F 2.2 GB, G 5.1 GB, H 12.3 GB free. Total ~475.9 GB (C), 280.7 GB (E), 673.1 GB (F), 931.5 GB (G/H). D/F tightest; G/H adequate for working set.
- UE toolchain: `UE4_ROOT` = G:\UnrealEngine_4.26_CARLA exists (engine present). `Plugins/Carla/Source/Carla/MapGen/LargeMapManager.cpp` NOT present in binary/package install; full source build requires vendored plugin source.
- Binary identity: Shipping binary `E:\CARLA\CARLA_0.9.16\CarlaUE4\Binaries\Win64\CarlaUE4-Win64-Shipping.exe` (91.5 MB, PDB 838 MB present) — build artifacts intact.
- No full source build attempted: storage tight; no MSVC version audit performed (MSVC presence assumed but not verified).
- Build feasibility: NOT ADMITTED; requires (a) vendored plugin source + MSVC + disk budget audit (build produces ~20+ GB Intermediate/Build); (b) storage headroom >30 GB; (c) operator approval.
- No build artifacts deleted/consolidated; no protected evidence deleted; `E:\wt\repair-map-realism-p0-837a8504` preserved; `reports/carla_runtime/` added.
