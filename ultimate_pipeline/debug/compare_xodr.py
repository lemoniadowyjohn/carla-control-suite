# debug/compare_xodr.py
import hashlib
from pathlib import Path

def md5(p: Path) -> str:
    h = hashlib.md5()
    h.update(p.read_bytes())
    return h.hexdigest()

if __name__ == "__main__":
    a = Path(r"PATH\TO\run1\08_final.xodr")
    b = Path(r"PATH\TO\run2\08_final.xodr")

    print("A:", a)
    print("B:", b)
    print("MD5 A:", md5(a))
    print("MD5 B:", md5(b))
    print("SAME:", md5(a) == md5(b))
