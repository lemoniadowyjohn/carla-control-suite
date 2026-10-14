# B6 Failure Recovery Matrix

Temporary-fixture fault injection across pipeline stages. Each stage
receives an injected fault and the observed recovery/failure-closed
behavior is recorded against the expected outcome.

| Stage | Injected Fault | Observed | Expected | PASS/FAIL |
|-------|----------------|----------|----------|-----------|
| XODR write | declared size mismatch after atomic write | IdentityVerificationError: INTEGRITY_MISMATCH_DECLARED_VS_DISK declared_sha256=103c57d924d324f23c74fe74305e79bfb15fe320077ed1e7a7909a90b45f9c17 declared_size=187 disk_sha256=103c57d924d324f23c74fe7430 | IdentityVerificationError: INTEGRITY_MISMATCH_DECLARED_VS_DISK | PASS |
| Enrichment | payload text mutated after base generation | enriched payload differs from base | enriched payload differs from base | PASS |
| Geometry freeze | XODR geometry mutated after freeze | GeometryFreezeError: geometry freeze mismatch: downstream stage would mutate frozen geometry (planView, road.length, or attachments) | GeometryFreezeError: geometry freeze mismatch | PASS |
| Tiles | no buildings assigned to tile | 0 | 0 | PASS |
| Registry update | candidate entry with invalid role | False | False | PASS |
| Candidate promotion | candidate parent hash mismatch | PromotionError: Promotion failed for cand-1: candidate parent hash does not match accepted parent | PromotionError | PASS |
| FBX/import-package staging | XODR file missing | failed | failed | PASS |

**Total stages: 7**

**Passed: 7, Failed: 0**
