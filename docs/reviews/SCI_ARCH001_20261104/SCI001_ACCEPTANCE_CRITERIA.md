# Acceptance criteria for the Codex SCI-001 provenance patch

**Status: NOT_RUN.** The SCI-001 patch does not exist yet; review it only after it does. A criterion
passes only with an executed command, output and SHA.

1. **Wording corrections**, made in a new docs file or commit; historical reports are not edited:
   - RQ2 hull-local values (0.0597 / 0.2206) separated from whole-map values (0.0415 / 0.0931); the
     bbox result (4.488) reported next to the hull result (2.683);
   - the RQ4 "CI excludes zero" sentence removed or replaced, and the RQ4 map pair named
     (Grid0821 / candidate_connectivity_repaired);
   - RQ1 scoped to "Osm2Odr stage, 3 runs, aggregate signature";
   - run `20261007_214826_524342` not cited as RQ1 evidence.
2. **Identity binding:** every RQ number in exported tables (`tools/export_thesis_tables.py`)
   carries:
   - the source artifact path;
   - its sha256, verified at export time, fail-closed on a mismatch;
   - the map pair, resolved through `map_registry` and never by glob or mtime.
   Test: tampering with one byte of a source makes the export fail.
3. **No silent defaults:** a missing source artifact fails the export (non-zero exit). The value is
   not emitted from cache or constants. Test it with the artifact removed.
4. **Superseded values kept:** 0.643 stays as `superseded_value` with its reason (GAP-010), and C19
   is untouched (`git diff --stat -- reports/` shows only new files).
5. **RQ3 and RQ5 stay DEFERRED:** a test asserts that the exporter emits no RQ3 or RQ5 numeric
   value while no admitted measurement exists.
6. **Missing identities listed:** the patch adds the rows of `INPUT_IDENTITY_AND_PROVENANCE_MATRIX.csv`
   that are UNKNOWN or prefix-only to a tracked "missing provenance" list. Nothing is invented.
7. **CI:** green on the patch SHA, plus the focused tests run locally, with output pasted.
8. **Independent review:** a different model family re-runs criteria 2, 3 and 5.
