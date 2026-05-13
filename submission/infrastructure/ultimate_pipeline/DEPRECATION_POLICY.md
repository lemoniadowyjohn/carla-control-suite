# Deprecation policy

A file is deprecated when:
- it duplicates functionality owned elsewhere, or
- it is a legacy entrypoint kept only for reproducibility.

Deprecated files:
- must contain a DEPRECATED header at top
- must not be imported by core pipeline
- may remain runnable as CLI if needed
