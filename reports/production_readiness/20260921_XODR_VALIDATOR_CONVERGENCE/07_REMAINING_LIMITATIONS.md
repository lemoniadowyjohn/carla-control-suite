# OC-59 remaining limitations (2026-09-21)

1. **No map regeneration or recertification.** Validator code and
   evidence only; the manual reference map's zero-width lanes are
   reported, not repaired.
2. **CARLA_LOAD_VERIFIED needs the runtime.** Static envelopes top
   out at VERIFIED_OFFLINE_STATIC by construction.
3. **Repair-domain checkers untouched.** check_carla_import_s and
   check_geometric_continuity keep their own thresholds (documented
   in 01_VALIDATOR_MATRIX.json); converging repair tolerances is a
   separate task.
4. **Deep laneLink semantics deferred** to the topology task; junction
   validation here is structural identity only.
5. **XSD ships unconfigured by default** (XODR_XSD_PATH unset): the
   honest status is NOT_CONFIGURED, and full schema conformance
   remains unproven until an official OpenDRIVE XSD is pinned.
6. **Duplicate-lane-ID / contactPoint severity split** between the
   offline validator (error) and the runtime preflight gate (warn/
   unchecked) is a documented, loader-safety-motivated divergence.
