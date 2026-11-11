# Runtime and resource checklist (preflight before the pilot and before any full run)

Per **volume**, not summed. Snapshot 2026-11-05: C 1.1 G, E 0.6 G, F 2.3 G, G 5.1 G (H is quarantined;
D and I hold personal data and are not used).

## Runtime (gate G0)
- [ ] CARLA 0.9.16 (`E:\CARLA\CARLA_0.9.16\CarlaUE4.exe`) started **by the operator** (agents may not
  start CARLA).
- [ ] `client.get_server_version()` returns a value, and `get_world()` succeeds within
  `[OPERATOR]` s. Port listening alone does not count.
- [ ] GPU: VRAM headroom before loading (4 earlier attempts used 5.9 of 6.1 GB and hung). Use a
  low-quality setting, a visible window first, and record the GPU driver version and temperature.
- [ ] Both maps load (`generate_opendrive_world`), and the topology hash is reproducible twice.
- [ ] Synchronous mode set and confirmed (`world.get_settings()`).

## Pilot volume (≤ 1 GB)
- [ ] Choose ONE volume with ≥ 2× the pilot estimate free (G: today).
- [ ] TMP/TEMP, the capture root, the logs and the manifests all go on that volume.
- [ ] Measure the actual bytes/frame per sensor after the pilot.

## Full run
- [ ] Estimate = `bytes/frame × frames/route × routes × 2 arms × (1 + weather arms)` + training temp
  + 3 checkpoints + 30% headroom. Must fit on **one** admissible volume.
- [ ] Today **no volume has room for a full 6-camera paired capture** (G: is the largest, at 5.1 GB).
  This is BLOCKED until the operator frees space (e.g. the orphaned September worktree copies on G:,
  an operator decision).
- [ ] Retention: raw captures until the admission decision; per-seed training temp deleted after each
  seed; checksum manifests and receipts never deleted.

## Training (G7)
- [ ] CPU-only environment (torch 2.9.1+cpu): estimate the wall time from a 1-batch timing on pilot
  data, before committing to 3 epochs × 3 seeds.
- [ ] Protocol hashes verified: rq5 `db7155fe…`, rq3 `5aa8ae24…`; plus the v2 CI amendment's hash if
  adopted.
- [ ] Launcher fail-safe (task 07) merged first. Today `train_launcher.py:541` would raise
  `AttributeError` on a contract error (`os.stderr`).
