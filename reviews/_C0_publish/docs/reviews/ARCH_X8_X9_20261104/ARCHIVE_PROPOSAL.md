# Proposal: content-addressed archive of the 2026-10-07 stage inputs

**Nothing has been uploaded.** Every option needs explicit operator approval. Check the quota and
budget **before** choosing; the limits below are as best known and must be checked against the
provider's current documentation and the account's settings.

## What must be archived
The 8 stage XODR files of run `20261007_214826_524342`: 1,063,561,918 bytes (about 1.06 GB). Their
sha256 values are in `PROVENANCE.json`. Stage 03 and stage 05 are byte-identical, so a
content-addressed store holds 7 unique blobs, about 0.92 GB. Optionally add the run's small JSON
receipts (`settings_snapshot.json`, `run_manifest.json`, `junction_connector_snap_report.json`,
`sumo_netconvert.log`).

## Options

| Option | Immutability | Fit | Check before use |
|---|---|---|---|
| **A. GitHub Release asset** on a dedicated tag (e.g. `evidence-run-20261007_214826_524342`) of `lemoniadowyjohn/carla-control-suite` | assets can be deleted by maintainers; pin by sha256 | simple, beside the code; per-file size limit (documented as 2 GiB) is above 150 MB | repo permissions; whether release assets count against any quota for this account |
| **B. Git LFS** on an evidence-only branch | content-addressed by LFS oid (sha256), so naturally verifiable | the repository already uses LFS (15 `filter=lfs` patterns, 62 LFS files) | the account's LFS storage and bandwidth quota (≈ 1 GB added); clones without `GIT_LFS_SKIP_SMUDGE=1` would pull it |
| **C. Zenodo (or an institutional repository)** | records are immutable once published, with a DOI | best for a thesis: citable and long-lived | upload limits and licence; the data contains OSM-derived content (ODbL attribution) |

**Recommendation:** **C** for the thesis record (immutable, citable), **mirrored** as **A** for
convenience. Avoid B unless the LFS quota is confirmed, because it changes clone behaviour for
everyone.

## Archive layout (for any option)
```
run_20261007_214826_524342/
  MANIFEST.json        # file, bytes, sha256, stage order, producing commit 22cf39ab (from run metadata), acquisition notes
  01_sanitized_20261007_214826_524342.xodr
  02_sumo_fixed_20261007_214826_524342.xodr
  03_topology_20261007_214826_524342.xodr
  04_elevation_20261007_214826_524342.xodr
  05_planview_20261007_214826_524342.xodr
  06_continuity_20261007_214826_524342.xodr
  06_geometry_frozen_20261007_214826_524342.xodr
  07_lanes_20261007_214826_524342.xodr
  receipts/            # optional small JSON + netconvert log
  REPRODUCE.md         # copy of this package's REPRODUCE.md
```
Original filenames and stage order are preserved, and raw bytes are uploaded unmodified (no
re-compression inside the XODR). Record the archive URL and the per-file hashes in a **new** evidence
manifest. Never edit `PROVENANCE.json` or an existing register.

## Operator steps
1. Choose an option and confirm the quota.
2. Approve the upload.
3. After upload, re-download one file and verify its sha256.
4. Add the URL to a new manifest file (backlog C0).
