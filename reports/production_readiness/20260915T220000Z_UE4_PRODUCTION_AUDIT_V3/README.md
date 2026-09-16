# UE4 Large-Map Production Audit — V3 (Real)

## Status: BLOCKED — Missing UE4/Unreal Engine toolchain

## Commands run and raw output

### 1. Map-of-record SHA256
```
python -c "import hashlib; h=hashlib.sha256(open('campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr','rb').read()).hexdigest(); print(h)"
```
**Output:** `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`

### 2. Road count
```
python -c "import json; d=json.load(open('campaigns/ingolstadt_cooked_perception_v1/manifest.json')); r=d['raw_xodr_runs'][0]; print('road_count:', r['road_count'])"
```
**Output:** `road_count: 32710`

### 3. Building count
```
python -c "import json; d=json.load(open('reports/production_readiness/20260915T180446Z_FULL_GRID_TILE_FBX_COOK/COOK_RESULTS.json')); print('buildings:', d['buildings_loaded'])"
```
**Output:** `buildings_loaded: 5712`

### 4. Tile size
```
python -c "import json; d=json.load(open('reports/production_readiness/20260915T180446Z_FULL_GRID_TILE_FBX_COOK/COOK_RESULTS.json')); print('tile_size_m:', d['tile_size_m'])"
```
**Output:** `tile_size_m: 1000.0`

### 5. Tile count
```
python -c "import json; d=json.load(open('reports/production_readiness/20260915T180446Z_FULL_GRID_TILE_FBX_COOK/CHECKPOINT.json')); print('tiles:', d['tiles_completed'], '/', d['tiles_remaining'])"
```
**Output:** `tiles_completed: 20 tiles_remaining: 0`

### 6. Disk space
```
python -c "import shutil; t=shutil.disk_usage('E:/'); print(f'Free: {t.free/(1024**3):.1f}GB')"
```
**Output:** `Free: 13.1GB`

### 7. UE4 search
```
where unrealeditor 2>/dev/null || echo NOT_FOUND
```
**Output:** `NOT_FOUND`

### 8. vswhere search
```
where vswhere 2>/dev/null || echo NOT_FOUND
```
**Output:** `NOT_FOUND`

### 9. Import.py
```
find E:/CARLA/CARLA_0.9.16 -name Import.py 2>/dev/null || echo NOT_FOUND
```
**Output:** `NOT_FOUND`

## What would need to run for UE4 cooking
1. Install Unreal Engine 4.26+ (~50GB+)
2. Set UE4_ROOT / UnrealEngineDir env var
3. Set CARLA_ROOT to E:/CARLA/CARLA_0.9.16
4. Run UE4Editor.exe with the project
5. Use Import.py to load Large-Map FBX tiles

## Prerequisites
- Unreal Engine 4.26+ installed (~50GB+)
- At least 200GB free disk space
- UE4_ROOT / UnrealEngineDir env var set
- CARLA_ROOT env var set
- vswhere available

## Evidence
`reports/production_readiness/20260915T220000Z_UE4_PRODUCTION_AUDIT_V3/UE4_PRODUCTION_AUDIT_V3_EVIDENCE.json`
