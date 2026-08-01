import os
from ultimate_pipeline.visualization.map_plotter import MapPlotter
import imageio.v2 as imageio  # pip install imageio


def generate_continuity_diff_gif(
    xodr_before: str,
    xodr_after: str,
    out_dir: str,
    base_name: str = "continuity_diff",
):
    os.makedirs(out_dir, exist_ok=True)

    before_stage = base_name + "_before"
    after_stage = base_name + "_after"

    # 1) Render previews using your existing MapPlotter
    MapPlotter.save_preview(xodr_before, out_dir, stage=before_stage)
    MapPlotter.save_preview(xodr_after, out_dir, stage=after_stage)

    before_png = os.path.join(out_dir, f"map_preview_{before_stage}.png")
    after_png = os.path.join(out_dir, f"map_preview_{after_stage}.png")

    if not (os.path.exists(before_png) and os.path.exists(after_png)):
        print("⚠ Could not find preview PNGs; GIF not created.")
        return

    # 2) Create a simple blinking GIF: before → after → before → after...
    frames = []
    for _ in range(3):
        frames.append(imageio.imread(before_png))
        frames.append(imageio.imread(after_png))

    gif_path = os.path.join(out_dir, f"{base_name}.gif")
    imageio.mimsave(gif_path, frames, duration=0.5)  # 0.5s per frame

    print(f"🎞 Continuity diff GIF saved → {gif_path}")
