POOL_EXHAUSTED

Reviewer pool status at time of write: EXHAUSTED.

All three reviewer fallback levels failed on dispatch:
- reviewer (primary): Free usage limit reached
- reviewer_alt (fallback 1): Returned POOL_OK on ping, then rate-limited on task dispatch
- reviewer_alt2 (fallback 2): Rate limit exceeded

Per O1 instructions: STOP. No placeholder review files created, no reviews claimed.

Automatic fallback wiring completed in this session (opencode.json):
- reviewer now carries fallback_models: openrouter/google/gemma-4-31b-it:free,
  openrouter/google/gemma-4-26b-a4b-it:free, openrouter/openrouter/free,
  opencode/nemotron-3.5-super-vl-free
- scout / test_triage / evidence_auditor / report_reader also carry fallback_models
  automatic chains (valid JSON, plugin @razroo/opencode-model-fallback installed,
  configuration reloaded successfully).

Google (Gemini-family) free models: openrouter/google/gemma-4-26b-a4b-it:free and
openrouter/google/gemma-4-31b-it:free are the only Google free models currently
available via OpenCode; no native google/gemini-* :free model exists in the catalog.
Both are wired and operational (scout_gemma_alt / scout_gemma_alt2) and were added as
automatic fallback candidates for the exhausted reviewer pool.

STOP.
