# Reproducibility

1. Fetch the repository and checkout the active engineering authority: `integration/production-large-map-20260918`. Do not rely on GitHub's current default `main` until the default-branch migration is completed.
2. Materialize governed LFS content with `git lfs install` and `git lfs pull`, then verify that pinned maps are real content rather than pointer stubs.
3. Verify `git status` is clean and audit all local worktrees using `docs/engineering/WORKTREE_HYGIENE.md`.
4. Install Python 3.12 dependencies with `pip install -r requirements.txt` and `pip install -e .`.
5. Run `up doctor` for environment/configuration checks.
6. Verify the current map identity through `verify_pinned_map('auto_map_of_record')`; use the verified receipt rather than filename dates or mtimes.
7. Run `python -m pytest -q` for the offline suite.
8. Run `up research status` and regenerate C19 evidence with `tools/run_c19_assembly.py`.
9. Run `up health --test-result PASS` to write the machine-readable health packet. If runtime verification was not executed, overall health must remain incomplete/offline-only.
10. For live CARLA claims, execute the self-hosted/runtime path separately and bind the result to the exact CARLA/UE build, map package, XODR SHA and client artifact used.

The reproducibility entrypoint is this sequence plus the pinned map, source, configuration, toolchain and evidence hashes. Large ignored run artifacts are optional integration evidence unless a specific scientific/release claim requires them; portable determinism claims use committed fixtures where possible.

Live RQ3/RQ5 experiments require the governed paired-capture protocol **and** a verified CARLA 0.9.16 runtime. Static contract completeness is not runtime capture evidence. Likewise, UE4 editor build success is not evidence that CarlaUE4, custom-map import, cook/package, or RPC succeeded.
