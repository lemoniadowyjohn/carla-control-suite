from __future__ import annotations

import time
import subprocess
from pathlib import Path

def run_and_tee(
    cmd: list[str],
    *,
    log_path: str | Path | None = None,
    cwd: str | Path | None = None,
    env: dict | None = None,
    prefix: str = "",
    heartbeat_sec: float = 10.0,
    logger=None,
) -> int:
    """Run a subprocess and STREAM its stdout/stderr live while also writing to a log file."""
    if log_path is not None:
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure unbuffered Python where possible
    if cmd and (cmd[0].lower().endswith("python.exe") or cmd[0].lower().endswith("python")):
        if "-u" not in cmd:
            cmd = [cmd[0], "-u", *cmd[1:]]

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    last_line_t = time.time()
    last_hb_t = time.time()

    log_f = None
    try:
        if log_path is not None:
            log_f = open(log_path, "w", encoding="utf-8", errors="replace")

        assert proc.stdout is not None
        for line in proc.stdout:
            last_line_t = time.time()
            msg = line.rstrip("\n")
            if prefix:
                msg = f"{prefix}{msg}"
            print(msg, flush=True)
            if logger is not None:
                try:
                    logger.info("%s", msg)
                except Exception:
                    pass
            if log_f is not None:
                try:
                    log_f.write(line)
                    log_f.flush()
                except Exception:
                    pass

        while True:
            rc = proc.poll()
            if rc is not None:
                return rc
            now = time.time()
            if heartbeat_sec > 0 and (now - last_hb_t) >= heartbeat_sec:
                quiet_for = now - last_line_t
                hb = f"{prefix}[heartbeat] child running, no output for {quiet_for:.1f}s ..."
                print(hb, flush=True)
                if logger is not None:
                    try:
                        logger.info("%s", hb)
                    except Exception:
                        pass
                if log_f is not None:
                    try:
                        log_f.write(hb + "\n")
                        log_f.flush()
                    except Exception:
                        pass
                last_hb_t = now
            time.sleep(0.25)
    finally:
        try:
            if log_f is not None:
                log_f.close()
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
