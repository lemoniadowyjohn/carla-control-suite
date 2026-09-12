# Determinism report — provenance note

`report.json` in this directory records, for 3 repeated Osm2Odr conversions of
the same pinned OSM input: per-run raw `sha256`/`md5`, a timestamp-normalized
hash, and a structural signature (roads/junctions/total length). It is the
portable, committed evidence behind RQ1's structural-determinism claim and the
"timestamps are the only byte-level source of nondeterminism" observation.

**Known gap (documented, not fabricated):** the committed `report.json` was
produced *before* tool/version capture was added, so it carries **no software
version binding**. The "timestamps are the only byte-level source" statement is
therefore bound to an *unrecorded* Osm2Odr/CARLA build. This is why RQ1's
`byte_nondeterminism_source` metric is (correctly) marked `BOUNDED`, not
`AUTHORITATIVE`, in `reports/post_audit_hardening/C19_THESIS_ASSEMBLY/rq_tables.json`.

**Forward fix:** `ultimate_pipeline/experiments/thesis/exp_osm_to_xodr_determinism.py`
now writes a `tool_versions` block (python, platform, and best-effort
CARLA/osm2odr versions) into every new `report.json`. Regenerating the
determinism evidence on a clean clone will produce a version-bound report:

```
python -m ultimate_pipeline.experiments.thesis.exp_osm_to_xodr_determinism \
    --osm <pinned_osm> --out-dir reports/post_audit_hardening/C15_RQ4_DR/determinism --runs 3
```

The historical `report.json` is intentionally left unmodified (evidence of what
was actually run); this note supersedes it additively rather than back-filling a
guessed version.
