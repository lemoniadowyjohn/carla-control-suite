# Repository Baseline

Generated: 2026-09-06T10:26:21Z

## Repository State

- Repository: `lemoniadowyjohn/carla-control-suite`
- Top level: `C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main`
- Source lineage branch at start: `fix/post-audit-phase-e-junctions-roundabouts-20260803`
- Stabilization branch created: `stabilize/research-release-20260905`
- HEAD: `b059a9d04ebb91c827224ca89406d16b0fe61d5e`
- September 5 observed baseline HEAD supplied by user: `2a3019cc78eeee726977e244f4a4e3dae296bd77`
- Dirty state after branch creation / before source edits: clean (`git status --porcelain=v1 --branch` returned only `## stabilize/research-release-20260905`)
- Remote: `origin https://github.com/lemoniadowyjohn/carla-control-suite.git`

## Python And Platform

- Python: `3.12.2 (tags/v3.12.2:6abddd9, Feb  6 2024, 21:26:36) [MSC v.1937 64 bit (AMD64)]`
- Platform: `Windows-11-10.0.26200-SP0`

## Test Baseline

Command:

```text
python -m pytest -q
```

Result:

```text
5734 passed, 79 skipped, 130 warnings in 350.60s (0:05:50)
```

Collection count in this checkout: `5813`.

## Map Of Record

Pinned auto map of record verified by `ultimate_pipeline.carla_tools.map_registry.verify_pinned_map("auto_map_of_record")`:

- Path: `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr`
- SHA256: `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`
- Bytes: `148949722`
- Frame: `rebased-to-local (dx=832671.676 dy=5458671.104)`
- Supersedes: `847d41bd11d85ff468f7e9611e1914959dad3b444ba83002911f20f86fd925bb`

Pinned manual reference verified by `verify_pinned_map("manual_grid0828")`:

- Path: `campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr`
- SHA256: `5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c`
- Bytes: `66530869`
- Frame: `UTM-32N (+proj=tmerc +lon_0=9 +k=0.9996 +x_0=500000)`

Pinned input hashes observed on disk:

- `campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm`: `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f`
- `campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_buildings_overpass.json`: `f3e8200118845910e136b478a68bd6eb67b985fef6357b98f76ecc6f520e30f5`
- `campaigns/ingolstadt_cooked_perception_v1/source/INPUTS_MANIFEST.json`: `b28bb033ee7c0f846a85552bfd319c48be825e5df1b4c67bcc84e327a4102182`
- `campaigns/ingolstadt_cooked_perception_v1/source/manual/MANUAL_MANIFEST.json`: `46b3be07290d31b20be4447494d189504cc79c6d4e2ea486186821ab4cd9dfa5`
- `campaigns/ingolstadt_cooked_perception_v1/manifest.json`: `d194279ff80a1a91861453c91a62ea61b38d238bc6cd33394ed8012ca52960fa`

Relevant git attributes:

- `campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr`: `filter=lfs diff=lfs merge=lfs text=unset`
- `campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm`: `filter=lfs diff=lfs merge=lfs text=unset`
- `campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_buildings_overpass.json`: `text=unset`

## Notes

- The local suite is already green at this HEAD; the four CI failures supplied in the mission appear to have been remediated before this baseline packet was written.
- `git status` required escalated execution because Git LFS attempted to create a temporary file under `.git/lfs/tmp` during status calculation inside the managed sandbox.
