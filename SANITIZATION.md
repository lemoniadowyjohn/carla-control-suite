# Public-release sanitization policy

This repository is intentionally designed as a **sanitized portfolio reconstruction** of map-quality engineering concepts. It must not contain private or employer-owned map data, repository history, customer geometry, internal project identifiers, proprietary screenshots, private source code, credentials, or undisclosed benchmark results.

## Allowed material

- Synthetic OpenDRIVE fixtures created specifically for this repository.
- Synthetic OSM XML created specifically for tests.
- Public OSM extracts, if later added with source/ODbL attribution and a reproducible download step.
- Original general-purpose Python implementations written for the public toolkit.
- Public standards/documentation references.

## Release checklist

1. Search for company/customer/project names and internal paths.
2. Search for credentials, tokens, email addresses and hostnames.
3. Verify all map files are synthetic or redistributable public data.
4. Re-run tests from a clean environment.
5. Regenerate reports from public fixtures only.
6. Inspect plots/screenshots for hidden proprietary context.
7. Keep portfolio claims scoped to what the public code demonstrates.
