try:
    import torch_geometric
    TORCH_GEOMETRIC_AVAILABLE = True
except Exception:
    TORCH_GEOMETRIC_AVAILABLE = False
