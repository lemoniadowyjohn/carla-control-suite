# O05 Candidate Lineage

## Authoritative Final Candidate

**File:** raw_xodr_run_1_epsg32632_header_pinned.xodr
**Path:** campaigns/ingolstadt_cooked_perception_v1/candidate/raw_xodr_run_1_epsg32632_header_pinned.xodr
**SHA-256:** ff2a05e7b00b8fc1bde38f569413223c03a4f4ac9c31eceb5a8592df47d0d17d
**Semantic SHA-256:** 019fc30e989e596b6dedccf82aefa4bad011b0c54ed3e5f185d8b262824ec84e
**Road Count:** 32,710
**Junction Count:** 3,646
**Size:** 82,318,919 bytes

## Lineage

1. **Raw Osm2Odr** → raw_xodr_run_1.xodr (baseline)
2. **Header Pinned** → raw_xodr_run_1_epsg32632_header_pinned.xodr (accepted candidate)
3. **Phase E** → Junction/roundabout hardening (enrichment)
4. **Phase F** → Elevation verification (F7-approved F5 candidate)
5. **Phase G** → Lane inventory (32,710 sections, 84,781 lane records)
6. **Phase H** → Signal enrichment
7. **Phase J** → OSM2World/Blender visual package
8. **J5R** → Corrected evidence set

## Selection Rationale

The header-pinned file is the last fully accepted full-map XODR in the governed lineage. All later phases are enrichment passes that operate on this candidate and produce visual/structural improvements, but do not produce a newer runtime XODR.

## Why Not Later-Phase XODR

Later phases (E through J) produce visual packages, enrichment evidence, and structural improvements, but they do not produce a newer runtime XODR file. The runtime XODR remains the header-pinned candidate.
