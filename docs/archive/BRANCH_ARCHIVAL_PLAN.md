# Branch Archival Plan

This document outlines the archival plan for non-production branches.

**Policy:** Do NOT delete any branches until this plan has been reviewed and approved by the project lead.

The following branches have been identified as potentially obsolete or superseded, but contain historical context or experimental value.

## Archival List

| Branch | Classification | Recommended Action |
| :--- | :--- | :--- |
| `main` | Historical (Disconnected) | Archive documentation, point to `integration/production-large-map-20260918`. |
| `fix/post-audit-phase-e-junctions-roundabouts-20260803` | Superseded | Archive as historical reference, do not use. |
| `stabilize/research-release-20260905` | Divergent | Archive as experimental state. |

## Execution Plan (REQUIRES APPROVAL)

1.  **Tagging:** Create immutable archive tags for these branches (e.g., `archive/20260924/main`).
2.  **Deletion:** Once tags are confirmed and documented, the remote branches can be safely deleted.
