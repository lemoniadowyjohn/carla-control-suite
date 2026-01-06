import os
import random
import numpy as np

def enforce_determinism(seed: int = 42):
    print(f"🔒 Enforcing deterministic mode with seed={seed}")

    # Python & NumPy
    random.seed(seed)
    np.random.seed(seed)

    # Python hash seed (important for consistent dict ordering)
    os.environ["PYTHONHASHSEED"] = str(seed)

    # PyTorch (optional)
    try:
        import torch
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    except Exception:
        # torch not installed; ignore silently
        pass

    return True
