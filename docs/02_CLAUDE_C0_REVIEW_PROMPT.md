# Claude C0 Review Prompt (drop verbatim into Claude Opus)

You are reviewing OpenCode's Stage 4 delivery for the Ingolstadt CARLA map
perception-candidate pipeline. The repo is at
`C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main` on branch
`fix/post-audit-phase-e-junctions-roundabouts-20260803`.

Governed facts OpenCode has already recomputed from primary files (do not
re-trust prior reports):

- Semantic parent = `reports/post_audit_hardening/20260807T000000Z/candidate_g_semantic_enriched.xodr`
  - sha256_lf_text = `d604ac393e12730ed276f5c865d0ef82c8a537b97bd8d79beeddd4c96863e470`
  - counts: roads=32710, junctions=3646, laneSections=32710, signals=3467, objects=0
  - verdict = SEMANTIC_PARENT_FROZEN
- Repaired parent = `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_fixed_final.xodr`
  - sha256_raw_bytes = `80ebb0054afd73ffdd51960b48679ff4689c72ed0abe75af5b2ae10a51395699`
  - signals=0 (negative control: must NOT be accepted as semantic parent)
- 12 connector-repair road IDs preserved: 50003,51425,51646,52738,54261,56874,
  57300,58404,62170,66369,68135,69106
- OSM crossing authority = 179 (reported ≈174 was stale); disposition:
  INSERTED=61, DUPLICATE_MERGED=5, OUTSIDE_MAP_SCOPE=35, AMBIGUOUS_MATCH_REJECTED=78
- Target CARLA = 0.9.16 (runtime server currently BLOCKED, B4 toolchain blocker)
- Crosswalk writing = NO_EXISTING_CAPABILITY (gap); object_writing,
  signal_digest, structural_digest, pedestrian_classification,
  semantic_replay/idempotency all REUSE_UNCHANGED canonical modules.

Read-only evidence files:
- N00 `S02_REUSE_CAPABILITY_MATRIX.csv`
- N01 `S03_SEMANTIC_PARENT_AUTHORITY.json`
- N02 `S04_PROTECTED_STRUCTURAL_DIGESTS.json`
- N03 `S05_TRAFFIC_CONTROL_DIGESTS.json`
- N05 `S03_OSM_CROSSING_AUTHORITY_RECOMPUTE.json` + Stage H `S07/S08/S09`
- N04 `docs/N04_CLAUDE_C0_PACKET.md` (full contract)

## Your review (Phase C0)

Evaluate the C0 semantic write contract in `docs/N04_CLAUDE_C0_PACKET.md`:

1. Crosswalk representation (§5.1): the proposed `<object type="crosswalk"
   id="crosswalk_{osm_id}" name="crosswalk_{subtype}" ...>` with a closed-quad
   `<outline>` via `cornerGlobal`, reusing `object_injector.ObjectInjector`.
   Field sourcing from the Stage H authority row (s, t, road_id, polyline
   bearing). Confirm or change.
2. Multi-road DUPLICATE_MERGED (§5.1, item 5.1a): default = option B
   (emit on primary road_ids[0], trace all road_ids in ledger). Confirm or
   switch to option A (split per road).
3. `name`/`subtype` mapping: `traffic_signals`→`crosswalk_signals`,
   `marked`→`crosswalk_marked`, `zebra`→`crosswalk_zebra`, else `crosswalk`.
   Confirm or require raw OSM `crossing=*` verbatim.
4. Outline quad: `start_m`–`end_m` centerline widened 4.0 m perpendicular
   (along-road) into a closed CCW quad. Approve `sweep_width_m=4.0` default?
5. Mutation allowlist (§6): additive only — ADD crosswalk `<object>` +
   `<objects>` containers; everything else byte-stable via N02/N03 digests.
   Approve?
6. Provenance (§7): `<userData>` `<crosswalk_origin osm_id source
   source_sha disposition/>` per object. Approve?
7. Integrity gates (§8) and test list (§9, T08–T19). Approve?
8. Negative control T01: `ingolstadt_fixed_final.xodr` (signals=0) must fail
   as a semantic parent. Confirm the gate.

## Decision

Return exactly one:

```
CLAUDE_SEMANTIC_WRITE_CONTRACT_ACCEPTED
```

or with specific edits. Do NOT return a variant string. After you return
`CLAUDE_SEMANTIC_WRITE_CONTRACT_ACCEPTED`, hand the response back verbatim to
OpenCode, which will then implement the production crosswalk writer (extending
the canonical `object_injector`/`building_extruder` pattern) and continue
through Stage 11 → C1 packet (N19). Until then, NO semantic mutation occurs.
