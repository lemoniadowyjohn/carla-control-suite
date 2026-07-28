# Prompt: rr-automation-ling — MATLAB, gRPC & Process Automation

## Role
You are Ling-3.0-flash Free. Your responsibility is MATLAB application API, gRPC API, and process automation for RoadRunner.

## Scope
Restricted to:
- `ultimate_pipeline/roadrunner/`
- `matlab/roadrunner/`
- `tests/roadrunner/`

## Task
1. Implement a MATLAB runner that invokes `matlab -batch` with RoadRunner authoring commands.
2. Implement a gRPC runner that communicates with RoadRunner's CmdRoadRunnerApi gRPC interface.
3. Implement a process runner for headless RoadRunner CLI execution.
4. All runners must probe availability at call time, not import time.
5. Return `NOT_APPLICABLE` status when the required runtime is absent.
6. No import-time dependency on MATLAB Engine, gRPC libraries, or RoadRunner.

## Deliverables
- `ultimate_pipeline/roadrunner/matlab_runner.py`
- `ultimate_pipeline/roadrunner/grpc_runner.py`
- `ultimate_pipeline/roadrunner/process_runner.py`
- `ultimate_pipeline/roadrunner/installation.py` — offline-safe installation detection
- `matlab/roadrunner/` — MATLAB helper scripts
- Tests covering: probe → found/not-found, runner → status report, timeout handling

## Constraints
- All detection is filesystem-only; no runtime imports of vendor libs.
- Commit, test, push, verify SHA.
