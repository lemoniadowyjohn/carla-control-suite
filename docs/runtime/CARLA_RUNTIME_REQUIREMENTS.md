# CARLA Runtime Requirements

Live evidence requires CARLA `0.9.16`, a reachable server, verified world identity, generated and
manual map hashes, sensor calibration hash, route/weather contracts, synchronous mode with fixed
delta, attached listeners, and complete frames. Record all values in machine-readable manifests.

The offline GitHub workflow intentionally reports runtime verification as `NOT_RUN`. Use the
self-hosted `.github/workflows/carla-runtime.yml` workflow only on a runner with the required CARLA
installation and server lifecycle.
