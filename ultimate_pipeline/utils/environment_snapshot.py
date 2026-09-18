import platform
import json
import hashlib
import subprocess


def write_environment_snapshot(out_path):
    data = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }

    try:
        pip = subprocess.check_output(["pip", "freeze"], text=True)
        data["pip_freeze"] = pip.splitlines()
        data["pip_freeze_sha256"] = hashlib.sha256(
            pip.encode("utf-8", errors="replace")
        ).hexdigest()
    except Exception:
        data["pip_freeze"] = []
        data["pip_freeze_sha256"] = ""

    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
