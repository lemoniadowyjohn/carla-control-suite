# V22 INDEPENDENT CHATGPT REVIEW PROMPT

Perform a comprehensive independent read-only engineering audit of this published CARLA Control Suite review candidate.

## Start with:
`reports/independent_review/V22_FINAL_HANDOFF/00_START_HERE.md`

## Verify implementation claims from actual source, not summaries.

## Inspect:
- V12–V15 fixes (experiment registry, resource fencing, Git provenance)
- Boolean-status contracts (is True strict coercion)
- Artifact publication (G2/G3 gates)
- Configuration authority (CRM, lease, terminal release)
- CARLA runtime identity (preflight, tick reports)
- Terminal release authority (lease, recovery)
- Source provenance (git SHA, git rev-parse)
- Packaging (wheel/sdist build, install test)
- CI security (secret scan, public-history scan)
- Geospatial correctness (map identity, CRS, lane width)
- Scientific evidence handling (RQ1–RQ5 classification)

## Review actual blocker-resolution status of:
- T2b (terminal authority)
- F15b (artifact certification)
- W-F (geometry review)
- W-B (RQ5 implementation)
- W-D (26-test acceptance suite)
- Candidate b (PR readiness)

## Verify:
- Whether claimed tests exercise real production paths
- Whether negative controls are effective
- False-success paths, incomplete implementations, contradictory source authority
- Missing tests, security risks, scientific-validity issues

## For each finding provide:
- Exact file/function/commit references
- Severity level
- Reproduction steps
- Expected invariant
- Recommended correction
- Owner
- Verification tests

## Distinguish confirmed defects from hypotheses.

## Do NOT:
- Merge or modify the repository
- Assume any test PASS without seeing execution logs
- Claim independent review has occurred

## Deliver:
1. Executive verdict
2. Verified implementation matrix
3. Confirmed defect register
4. Regression coverage gaps
5. Specialist integration assessment
6. Scientific evidence classification
7. GitHub CI/security assessment
8. Prioritized work packages
9. Final ACCEPT / REQUIRES_CHANGES / NOT_VERIFIED recommendation

## Review start URL:
`reports/independent_review/V22_FINAL_HANDOFF/00_START_HERE.md`
