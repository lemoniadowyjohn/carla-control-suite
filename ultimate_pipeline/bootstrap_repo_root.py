import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SUBMISSION_INFRA = REPO_ROOT / "submission" / "infrastructure"
if str(SUBMISSION_INFRA) not in sys.path:
    sys.path.insert(0, str(SUBMISSION_INFRA))
