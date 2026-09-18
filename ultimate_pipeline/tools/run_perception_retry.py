from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.core.carla_utils import (
    autostart_carla_if_needed,
    ensure_carla_ready,
    restart_carla,
)


MAP_TRAVEL_RISK_GRID0821 = "MAP_TRAVEL_RISK_GRID0821"


def _parse_args(argv: Sequence[str]) -> Tuple[argparse.Namespace, List[str]]:
    ap = argparse.ArgumentParser(
        description=(
            "Retry wrapper around run_perception_safe.py with CARLA restart/recovery."
        )
    )
    ap.add_argument("--town", required=True, help="Target town/map name.")
    ap.add_argument("--calib", required=True, help="Calibration JSON path.")
    ap.add_argument("--out", required=True, help="Output directory for run_perception_safe.")
    ap.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum run_perception_safe attempts (default: 3).",
    )
    ap.add_argument(
        "--wait-carla-ready",
        type=float,
        default=45.0,
        help="Seconds to wait for CARLA readiness after restart (default: 45).",
    )
    ap.add_argument(
        "--seg",
        action="store_true",
        help="Forward --seg to run_perception_safe.",
    )
    return ap.parse_known_args(list(argv))


def _extract_arg_value(args: Sequence[str], flag: str) -> str | None:
    for idx, token in enumerate(args):
        if token == flag and idx + 1 < len(args):
            return str(args[idx + 1])
        if token.startswith(flag + "="):
            return token.split("=", 1)[1]
    return None


def _extract_host_port(forward_args: Sequence[str]) -> Tuple[str, int]:
    host = _extract_arg_value(forward_args, "--host") or str(
        getattr(SETTINGS, "CARLA_HOST", "127.0.0.1")
    )
    port_raw = _extract_arg_value(forward_args, "--port")
    try:
        port = int(port_raw) if port_raw is not None else int(getattr(SETTINGS, "CARLA_PORT", 2000))
    except Exception:
        port = int(getattr(SETTINGS, "CARLA_PORT", 2000))
    return host, port


def _read_json_if_dict(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_retry_log_path(out_dir_raw: str) -> Path:
    out_dir = Path(str(out_dir_raw))
    if out_dir.is_dir():
        return out_dir / "session_retry_log.json"
    return Path.cwd() / "session_retry_log.json"


def _run_perception_safe(
    *, town: str, calib: str, out: str, seg: bool, passthrough: Sequence[str]
) -> subprocess.CompletedProcess[str]:
    forwarded = list(passthrough)
    if seg:
        # Compatibility flag: run_perception_safe currently enables segmentation by default.
        forwarded = [token for token in forwarded if token != "--no-seg"]

    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.run_perception_safe",
    ]
    if _extract_arg_value(forwarded, "--manual-town") is None:
        cmd.extend(["--manual-town", str(town)])
    cmd.extend(
        [
            "--town",
            str(town),
            "--calib",
            str(calib),
            "--out",
            str(out),
        ]
    )
    cmd.extend(forwarded)
    return subprocess.run(cmd, text=True, check=False)


def _recover_carla(*, town: str, host: str, port: int, wait_ready_s: float) -> bool:
    if not restart_carla(host=host, port=port):
        return False
    client = autostart_carla_if_needed(host=host, port=port, timeout_s=float(wait_ready_s))
    if not ensure_carla_ready(
        client, retries=max(1, int(wait_ready_s)), delay_s=1.0, require_map=True
    ):
        return False
    if str(town or "").strip().lower() == "grid0828":
        client.load_world(str(town))
        if not ensure_carla_ready(
            client, retries=max(1, int(wait_ready_s)), delay_s=1.0, require_map=True
        ):
            return False
    return True


def _failure_reason_for_attempt(
    result: subprocess.CompletedProcess[str], carla_status: Dict[str, Any]
) -> str:
    reason = str(carla_status.get("failure_reason", "") or "").strip()
    if reason:
        return reason
    detail = str(carla_status.get("failure_detail", "") or "").strip()
    if MAP_TRAVEL_RISK_GRID0821 in detail:
        return MAP_TRAVEL_RISK_GRID0821
    if bool(carla_status.get("carla_failed", False)):
        return "carla_failed_true"
    return f"run_perception_safe_exit_{int(result.returncode)}"


def _write_retry_log(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args, passthrough = _parse_args(sys.argv[1:] if argv is None else argv)
    max_attempts = max(1, int(args.max_attempts))
    wait_ready_s = max(1.0, float(args.wait_carla_ready))
    host, port = _extract_host_port(passthrough)
    status_path = Path(str(args.out)) / "carla_status.json"
    retry_log_path = _resolve_retry_log_path(str(args.out))

    attempts: List[Dict[str, Any]] = []
    final_status = "failed"
    exit_code = 1

    for attempt in range(1, max_attempts + 1):
        started = time.perf_counter()
        result = _run_perception_safe(
            town=str(args.town),
            calib=str(args.calib),
            out=str(args.out),
            seg=bool(args.seg),
            passthrough=passthrough,
        )
        elapsed_s = float(time.perf_counter() - started)
        carla_status = _read_json_if_dict(status_path)
        carla_failed = bool(carla_status.get("carla_failed", False))
        success = int(result.returncode) == 0 and not carla_failed

        if success:
            attempts.append(
                {
                    "attempt_number": int(attempt),
                    "exit_code": int(result.returncode),
                    "failure_reason": None,
                    "duration_s": round(elapsed_s, 3),
                    "carla_restarted": False,
                }
            )
            final_status = "success"
            exit_code = 0
            break

        failure_reason = _failure_reason_for_attempt(result, carla_status)
        carla_restarted = False

        if failure_reason == MAP_TRAVEL_RISK_GRID0821:
            attempts.append(
                {
                    "attempt_number": int(attempt),
                    "exit_code": int(result.returncode),
                    "failure_reason": MAP_TRAVEL_RISK_GRID0821,
                    "duration_s": round(elapsed_s, 3),
                    "carla_restarted": False,
                }
            )
            print(
                "MAP_TRAVEL_RISK_GRID0821: load Grid0821 manually in CARLA and rerun with --use-current-world."
            )
            final_status = "operator_intervention_required"
            exit_code = 2
            break

        if attempt < max_attempts:
            try:
                carla_restarted = _recover_carla(
                    town=str(args.town),
                    host=str(host),
                    port=int(port),
                    wait_ready_s=float(wait_ready_s),
                )
                if not carla_restarted:
                    failure_reason = f"{failure_reason};carla_restart_failed"
            except Exception as exc:
                failure_reason = f"{failure_reason};restart_exception:{exc.__class__.__name__}:{exc}"
                carla_restarted = False

        attempts.append(
            {
                "attempt_number": int(attempt),
                "exit_code": int(result.returncode),
                "failure_reason": str(failure_reason),
                "duration_s": round(elapsed_s, 3),
                "carla_restarted": bool(carla_restarted),
            }
        )

        if attempt >= max_attempts:
            final_status = "failed"
            exit_code = 1

    payload = {
        "town": str(args.town),
        "max_attempts": int(max_attempts),
        "final_status": str(final_status),
        "attempts": attempts,
    }
    _write_retry_log(retry_log_path, payload)
    print(f"[run_perception_retry] wrote {retry_log_path}")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
