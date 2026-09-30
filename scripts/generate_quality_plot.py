from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from carla_map_quality_toolkit.alignment import SE2Transform, estimate_se2

out = Path("docs")
out.mkdir(exist_ok=True)
reference = np.column_stack([np.linspace(0, 50, 101), 0.5 * np.sin(np.linspace(0, 2.5, 101))])
observed = SE2Transform(angle_rad=0.01, tx=0.30, ty=-0.15).apply(reference)
observed[:, 1] += 0.03 * np.sin(np.linspace(0, 8.0, 101))
fitted, _ = estimate_se2(observed, reference)
aligned = fitted.apply(observed)

fig, ax = plt.subplots(figsize=(9, 4.8))
ax.plot(reference[:, 0], reference[:, 1], label="Reference geometry", linewidth=2)
ax.plot(observed[:, 0], observed[:, 1], label="Before SE(2) alignment", linestyle="--")
ax.plot(aligned[:, 0], aligned[:, 1], label="After alignment", linestyle=":")
ax.set_title("Synthetic map-geometry quality check")
ax.set_xlabel("Local X [m]")
ax.set_ylabel("Local Y [m]")
ax.set_aspect("equal", adjustable="datalim")
ax.grid(True, alpha=0.25)
ax.legend()
fig.tight_layout()
fig.savefig(out / "quality_report_example.png", dpi=180)
fig.savefig(out / "quality_report_example.svg")
plt.close(fig)
