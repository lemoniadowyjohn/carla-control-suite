# Deprecation policy

A file is deprecated when:
- it duplicates functionality owned elsewhere, or
- it is a legacy entrypoint kept only for reproducibility.

Deprecated files:
- must contain a DEPRECATED header at top
- must not be imported by core pipeline
- may remain runnable as CLI if needed

## SYS-001 status (2026-08-02)
This tree is the archived snapshot / migration donor. The canonical production
package is the repo-root ultimate_pipeline/. Do not import this tree as a
second production package; port modules on demand and mark them deprecated.
