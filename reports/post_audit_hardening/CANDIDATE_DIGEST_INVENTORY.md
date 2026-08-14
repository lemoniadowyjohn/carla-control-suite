# Candidate XODR Digest Inventory

Dir: `campaigns/ingolstadt_cooked_perception_v1/candidate/`  ·  generated 2026-08-13 (batch 3).
Full sha256 + byte size + git tracking for every candidate `.xodr`. Feeds the pre-run gate
`tools/verify_candidate_digest.py`.

| filename | sha256 | bytes | git |
|---|---|--:|---|
| ingolstadt_perception_final_repaired.xodr | `6bac3570ce8f4230836ace27ec26155bbed58171567a6e0afd47e710c86dcb02` | 82,593,544 | **untracked** |
| ingolstadt_fixed_final.xodr | `80ebb0054afd73ffdd51960b48679ff4689c72ed0abe75af5b2ae10a51395699` | 82,935,087 | tracked |
| ingolstadt_perception_final_repaired_v2.xodr | `1f2b5ff0570d0a577507a9a273608df07689f8f6b68f3708855a2e855f76131a` | 81,007,367 | untracked |
| ingolstadt_perception_final.xodr | `248ffbbe6a1aa2a9cbd4330a69ad1c1680d39698e2d186dd45f5a2eb91c5db6c` | 81,007,405 | tracked |
| provisional_pre_c0_ingolstadt_perception.xodr | `b5b389270bd2ed4c17ca15029c4d4787b684dde201465d002b52de5c69fc1aa6` | 82,589,796 | tracked |
| raw_xodr_run_1.xodr | `6044a87d8d6e116b444fe4413a46ab97085033def004b62d011233f4ddc0e93d` | 82,318,841 | tracked |
| raw_xodr_run_1_epsg32632_header_pinned.xodr | `ff2a05e7b00b8fc1bde38f569413223c03a4f4ac9c31eceb5a8592df47d0d17d` | 82,318,919 | tracked |
| raw_xodr_run_2.xodr | `c8c57c7282f483592802307aa9ccc839eedf1468279690afa612b0bcd59734c2` | 82,318,841 | tracked |

## Role adjudication (Claude Opus 4.8, 2026-08-13)

| sha256 (short) | file | ROLE |
|---|---|---|
| `6bac3570` | ingolstadt_perception_final_repaired.xodr | **SIGNED_TARGET** — authoritative crash-safe candidate (user-confirmed 2026-08-13). The live run + `run_n_certify` must use this. |
| `80ebb005` | ingolstadt_fixed_final.xodr | **SUPERSEDED_BROKEN** — P04 currently pins this → G2 `WRONG_CANDIDATE_HASH`; crash-unsafe predecessor. |
| `1f2b5ff0` | ingolstadt_perception_final_repaired_v2.xodr | **SUPERSEDED_EXPERIMENT** — v2, NOT authoritative (user-confirmed). Do not certify. |
| `248ffbbe` | ingolstadt_perception_final.xodr | PRE-REPAIR — perception_final before the length/crash repair. |
| `b5b38927` | provisional_pre_c0_… | PROVISIONAL (pre-C0). |
| `6044a87d` / `c8c57c72` | raw_xodr_run_1 / run_2 | RAW_OSM_XODR — upstream generation runs. |
| `ff2a05e7` | raw_xodr_run_1_epsg32632_header_pinned.xodr | RAW_EPSG32632_PINNED — CRS-pinned raw XODR referenced by VXR `C55V01a` in the ledger. |

**Provenance inversion (important):** the SIGNED_TARGET `6bac3570` is **untracked** (~80 MB, gitignored, anchored
by sha256 in evidence), while the SUPERSEDED_BROKEN `80ebb005` is **tracked**. Always digest-verify `6bac3570`
before a live run — it exists only on this workstation.
