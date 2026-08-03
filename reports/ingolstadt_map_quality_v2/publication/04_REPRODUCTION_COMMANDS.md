# Reproduction Commands

This document provides commands to reproduce verification checks for the Ingolstadt map quality v2 campaign.

## Environment

- **Repository**: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main`
- **External workspace**: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_improvement\ingolstadt-map-quality-v2-202608`
- **Baseline commit**: `877e9aef41f733a3ecf980a4559ec6bd359037bf`
- **Branch**: `improvement/ingolstadt-map-quality-v2-202608`

## Prerequisites

```powershell
cd C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main
python -m pip install -e .
pip install -r requirements.txt
```

## 1. Verify Coordinate Reprojection

### Check XODR geoReference and coordinate magnitude

```powershell
python -c "
import xml.etree.ElementTree as ET
tree = ET.parse('reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/candidate_actual_reprojection.xodr')
root = tree.getroot()
hdr = root.find('header')
geo = hdr.find('geoReference')
print('geoReference:', (geo.text or '').strip())
road = root.find('.//road')
geom = road.find('planView/geometry')
print('First geometry x,y:', geom.get('x'), geom.get('y'))
"
```

Expected output: coordinates in UTM zone 32N range (678942.92, 5402201.68), `tmerc` projection.

### Run coordinate tests

```powershell
python -c "
import json
with open('reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/coordinate_tests.json') as f:
    tests = json.load(f)
print('Round-trip passed:', tests['round_trip']['passed'])
print('Inverse consistency passed:', tests['inverse_consistency']['passed'])
print('All tests passed:', tests['all_tests_passed'])
print('Verdict:', tests['verdict'])
"
```

Expected output: `True` for round-trip, inverse consistency, and all tests; verdict `COORDINATES_REPROJECTED_AND_VERIFIED`.

## 2. Verify File Hashes

### Coordinate-corrected candidate

```powershell
python -c "
import hashlib
h = hashlib.sha256(open('reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/candidate_actual_reprojection.xodr','rb').read()).hexdigest()
print(h)
# Expected: 3d55a86e47192e6d8558820d8acfd553eb7f665cf9726e67853f9f1a060bc702
"
```

### Rejected connectivity repair candidate (external)

```powershell
python -c "
import hashlib
path = r'C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_improvement\ingolstadt-map-quality-v2-202608\work_package_02_connectivity\rejected_attempt_v1\candidate_connectivity_repaired.xodr'
h = hashlib.sha256(open(path,'rb').read()).hexdigest()
print(h)
# Expected: c3dc29d3f570d929cbe664961446ea76fd3b8c74b0f4668ade99a67995a7ca43
"
```

## 3. Verify Git LFS Tracking

```powershell
git lfs ls-files
git check-attr filter -- reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/candidate_actual_reprojection.xodr
git check-attr filter -- reports/ingolstadt_map_quality_v2/work_package_02_connectivity/candidate_connectivity_repaired.xodr
```

Expected: `filter: lfs` for `.xodr` files.

## 4. Verify Connectivity Repair Rejection

### Check promotion block

```powershell
python -c "
import json
with open('reports/ingolstadt_map_quality_v2/work_package_02_connectivity/rejected_attempt_v1/promotion_block.json') as f:
    pb = json.load(f)
print('promotion_allowed:', pb['promotion_allowed'])
print('verdict:', pb['verdict'])
print('campaign_verdict:', pb['campaign_verdict'])
"
```

Expected output:
- `promotion_allowed: False`
- `verdict: CONNECTIVITY_REPAIR_REJECTED`
- `campaign_verdict: COORDINATE_VERIFIED_CONNECTIVITY_REJECTED`

### Check WP2C verdict

```powershell
python -c "
import json
with open('reports/ingolstadt_map_quality_v2/work_package_02_connectivity/rejected_attempt_v1/verification/01_METRIC_DEFINITIONS.json') as f:
    md = json.load(f)
print('Metric definitions loaded:', len(md.get('metrics', [])) if 'metrics' in md else 'N/A')
"
```

### Check rejected repair count

```powershell
python -c "
with open('reports/ingolstadt_map_quality_v2/work_package_02_connectivity/rejected_attempt_v1/verification/04_REJECTED_REPAIRS.csv') as f:
    lines = f.readlines()
print('Rejected repair count (excl header):', len(lines) - 1)
# Expected: 6132
"
```

## 5. Verify Baseline Authority

```powershell
python -c "
import json
with open('reports/ingolstadt_map_quality_v2/CAMPAIGN_POINTER.json') as f:
    cp = json.load(f)
print('Campaign:', cp['campaign'])
print('Branch:', cp['branch'])
print('Baseline commit:', cp.get('tag_commit', 'N/A'))
print('Work packages:', cp['work_packages'])
"
```

## 6. Run Repository Tests

```powershell
python -m pytest -q
```

## 7. Verify Commit History

```powershell
git log --oneline --decorate 877e9aef..HEAD
git diff --stat 877e9aef..HEAD
git diff --check 877e9aef..HEAD
```
