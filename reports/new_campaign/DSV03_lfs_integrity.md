# DSV03 — LFS / Artifact-Integrity Verification

**Model:** DeepSeek V4 Light · **Mode:** READ-ONLY · **Task ID:** DSV03-06-REPORTS
**Branch:** `integration/governed-map-quality-20260729` · **Base SHA:** `64139d3b2560cb7f00061092f22b481adf963af8`
**Verdict:** `LFS_INTEGRITY_VERIFIED`

## 1. LFS pointer inventory (`git lfs ls-files` @ 64139d3b)

Exactly 4 campaign artifacts are LFS-tracked — no more, no fewer:

| # | File | LFS oid (sha256) | LFS size (B) |
|---|------|------------------|--------------|
| 1 | `campaigns/ingolstadt_cooked_perception_v1/candidate/raw_xodr_run_1.xodr` | `6044a87d8d6e116b444fe4413a46ab97085033def004b62d011233f4ddc0e93d` | 82,318,841 |
| 2 | `campaigns/ingolstadt_cooked_perception_v1/candidate/raw_xodr_run_1_epsg32632_header_pinned.xodr` | `ff2a05e7b00b8fc1bde38f569413223c03a4f4ac9c31eceb5a8592df47d0d17d` | 82,318,919 |
| 3 | `campaigns/ingolstadt_cooked_perception_v1/candidate/raw_xodr_run_2.xodr` | `c8c57c7282f483592802307aa9ccc839eedf1468279690afa612b0bcd59734c2` | 82,318,841 |
| 4 | `campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm` | `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f` | 11,154,738 |

All pointer blobs are 133–175 B LFS pointer files (`version https://git-lfs.github.com/spec/v1`), NOT raw bytes in the tree.

## 2. oid ↔ manifest sha256 cross-check

| File | LFS oid | `manifest.json` (top) | `candidate/manifest.json` | `source/manifest.json` | `agent_sync.yaml` | Match |
|------|---------|----------------------|---------------------------|------------------------|-------------------|-------|
| raw_xodr_run_1.xodr | `6044a87d…` | sha256 `6044a87d…` @ L257 · byte_size 82,318,841 | sha256 `6044a87d…` @ L213 · byte_size 82,318,841 | — | `raw_xodr_sha256: 6044a87d…` | ✅ |
| header_pinned | `ff2a05e7…` | sha256 `ff2a05e7…` @ L50 · byte_size 82,318,919 | sha256 `ff2a05e7…` @ L6 · byte_size 82,318,919 | — | `pinned_xodr_sha256: ff2a05e7…` | ✅ |
| raw_xodr_run_2.xodr | `c8c57c72…` | sha256 `c8c57c72…` @ L463 · byte_size 82,318,841 | sha256 `c8c57c72…` @ L419 · byte_size 82,318,841 | — | — | ✅ |
| ingolstadt_authoritative.osm | `b9e07465…` | sha256 `b9e07465…` @ L16 · byte_size 11,154,738 | — | sha256 `b9e07465…` @ L6 · byte_size 11,154,738 | `source_osm_sha256: b9e07465…` | ✅ |

4/4 files: oid == manifest sha256 AND size == manifest byte_size. No mismatches.
Note: run_1 / pinned / run_2 share `semantic_sha256 019fc30e…` (header-only pin, structural content identical by design) — consistent, not an anomaly.

## 3. Routing rules

- `.gitattributes` (tracked, 2 rules):
  `campaigns/ingolstadt_cooked_perception_v1/**/*.xodr filter=lfs diff=lfs merge=lfs -text`
  `campaigns/ingolstadt_cooked_perception_v1/**/*.osm  filter=lfs diff=lfs merge=lfs -text`
- `git check-attr filter` → xodr: `lfs` ✅, osm: `lfs` ✅, manifest.json: `unspecified` (correct).
- `candidate/.gitignore` no longer ignores `*.xodr` (rule replaced by LFS-governance comment); `git check-ignore -v candidate/raw_xodr_run_1.xodr` → empty (NOT ignored) ✅.

## 4. Tree state

- `git status --porcelain=v2 -- campaigns/ .gitattributes` → clean (no output) ✅
- Local HEAD `64139d3b` == upstream `origin/integration/governed-map-quality-20260729` ✅ (4 LFS objects, 258 MB, uploaded at push)

## Conclusion

B2's LFS closure is real: bytes are in the tree as LFS pointers whose oids reproduce the authoritative manifest sha256s exactly. Hashes remain the authority and match byte-for-byte.
