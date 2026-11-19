# V131 dependency DAG

Evidence is a snapshot from 2026-11-19. Production base: `225ed15d0da6444cc257835ca777aba281553f3c` (`integration/production-large-map-20260918`). Candidate before this report commit: `1085e00031ffae99ca770ee963dc6f90ffafde72`.

## Integrated, exact source tips

- `#69` tip `e798d778a18840938cdb30a88d0d4eec5c0786e3`, ancestry `#66 -> #68 -> #69` verified. Includes #66/#68, merged once.
- `#65` `4026fb5365e4dbfa0ca9de33c203b4f4911c8566`, merged as native-intrinsics layer; overlaps calibration and remains subject to independent physical review.
- `#67` `66c1459d9a55a2482b7df740e628301ee8bdd726`, coordinate-frame contract; RQ3 geographic route executor remains unwired.
- `#49` `d30a0544e385e4b353f125a61cd678683d2c2a11`; polynomial width fuzzer.
- `#56` `af22f82c5095462b2bd2ae0f2a1c6b3bd09eba6`; feature-gap missingness semantics.
- `#52 -> #55` with #54's unique test-argument edits already present in #55 (`4ad05dc3b5c67df24551468d385a0447a73fc106`); integrated #55 only.
- `#50` `230f4aeb17d356c45fe8a4fb6e02272c79c0822a`; semantically complementary RQ5 provenance layer, integrated alongside #55.
- `#35 -> #60 -> #64` exact ancestry verified; #64 `cc93b03a48ad9388e9d604630cb6bd6cc40c80be` integrated after manual overlap review of `run_perception_safe.py`.
- V129 T1 partial fix `00f059fbc067aace82212e2b768f016b0bd0d71b`; T2 mirror sync `8b8c53d10be6613d63ee336e40add93681c90c01`.

## Excluded / pending

- #70 `32610a41442ba98c633c407bd4762abd167133a6`: offline tests fail; wait for OC-A correction.
- #63 `6e6ac76fbaa03a83f9b601684b8bedf59a0f2591`: green checks, but not integrated pending OC-A successor and independent review.
- #37/#58 lease design: #58 duplicates #37 head; two unresolved recovery threads and not all checks green. Excluded pending thread-level/source adjudication and WSL/NTFS durability test.
- #39 and #57 are not ancestor-related despite the intended dependency; reconcile semantically before any ingestion. #45/#46 are based on older #40 intermediate, not current #40 tip.
- #35/#60 CI failures are superseded by green #64 exact tip; only #64 integrated.
- GUI #34/#43/#44 have separate branch ancestry and are excluded. #31/#36 failed CI and are excluded.
- #30 -> #48 -> #59 remains separate from #63 release-contract line. #30 has unresolved inline review threads; no threads auto-resolved.

`MERGED_IN_CANDIDATE` records source ancestry only. It does not imply production merge, live CARLA operation, dataset admission, or scientific completion.