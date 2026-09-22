import tempfile
import subprocess
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
fake = tmp / "fake_blender"
fake.write_text("#!/bin/sh\necho 'not blender'\nexit 1\n", encoding="utf-8")
fake.chmod(0o755)

result = subprocess.run([str(fake), "--version"], capture_output=True, text=True, timeout=30)
print('returncode:', result.returncode)
print('stdout:', result.stdout)
print('stderr:', result.stderr)