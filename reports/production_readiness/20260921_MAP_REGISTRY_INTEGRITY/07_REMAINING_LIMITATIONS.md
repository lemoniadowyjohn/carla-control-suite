# OC-58 remaining limitations (2026-09-21)

1. **No map regeneration or recertification.** Pins, bytes and the production
   map itself are untouched. The registry answers "what exact bytes does
   `auto_map_of_record` name" — it does not re-attest map quality.
2. **Historical files trusted when pruned.** If a `supersedes_path` file is
   absent from disk, the chain link is a WARNING (metadata-only trust), not
   an error. In this checkout every superseded auto file is present and
   hash-verified, so no such warning is live.
3. **Cooked-name registry untouched.** `COOKED_MAP_ALIASES` (CARLA runtime
   names) is out of scope; only `PINNED_MAP_REGISTRY` is hardened.
4. **Receipt is call-time evidence.** `verify_pinned_map` proves content at
   call time; long-lived processes must re-verify rather than cache receipts.
5. **Cross-role override is a loaded gun.** `allow_cross_role_content: true`
   exists for tests only; any production use must be called out in review.
6. **External absolute paths remain a test affordance**
   (`allow_external_absolute_paths`); production audit requires
   repository-contained paths.
7. **Frames are identity, not geometry.** Structured frame fields pin which
   frame a map claims, not the correctness of any transform. Historical
   entries stay `LEGACY_TEXT_ONLY` rather than carrying invented values.
