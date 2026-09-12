# Reproducibility

1. Checkout the stabilization lineage and verify `git status` is clean.
2. Install Python 3.12 dependencies with `pip install -r requirements.txt` and `pip install -e .`.
3. Run `up doctor` for environment/configuration checks.
4. Run `python -m pytest -q` for the offline suite.
5. Run `up research status` and regenerate C19 evidence with `tools/run_c19_assembly.py`.
6. Run `up health --test-result PASS` to write the machine-readable health packet.

The reproducibility entrypoint is this sequence plus the pinned map and evidence hashes. Large ignored
run artifacts are optional integration evidence; portable determinism claims use committed fixtures.
Live RQ3/RQ5 experiments require the protocol and a verified CARLA 0.9.16 runtime.
