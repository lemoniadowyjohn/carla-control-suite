| Failure Type                         | Detection Signal                     | Mitigation                                                                 | Status    |
|-------------------------------------|--------------------------------------|-----------------------------------------------------------------------------|-----------|
| pytest import-time argparse failure | Import-time exception during testing | Refactored CLI parsing to runtime execution, enabling safe pytest imports  | Completed |
| CARLA RPC connection refused        | Connection timeout or refusal        | Simulator availability probe prior to CARLA-dependent stages               | Completed |
| CARLA crash on map load             | Simulator crash logs                 | Deterministic failure logging and controlled reproduction of input artifacts | Completed |
| zero-length roadMark segments       | OpenDRIVE validation failure         | Sanitization of invalid roadMark definitions prior to simulation            | Completed |
| negative-s tile geometry            | Tiling QA discrepancy reports        | Geometry correction and explicit reporting during tiling                    | Completed |
