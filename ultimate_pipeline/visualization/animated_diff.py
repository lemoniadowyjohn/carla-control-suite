# ultimate_pipeline/visualization/animated_diff.py

import os
from PIL import Image


class AnimatedDiff:
    """
    Build an animated GIF showing a smooth transition between
    two map previews (e.g. before/after continuity).
    """

    @staticmethod
    def run(before_png, after_png, gif_out, frames=12, duration_ms=150):
        if not os.path.exists(before_png):
            print(f"❌ before_png missing: {before_png}")
            return
        if not os.path.exists(after_png):
            print(f"❌ after_png missing: {after_png}")
            return

        img_a = Image.open(before_png).convert("RGBA")
        img_b = Image.open(after_png).convert("RGBA")

        # resize to match
        if img_a.size != img_b.size:
            img_b = img_b.resize(img_a.size, Image.BILINEAR)

        all_frames = []

        # fade A → B
        for i in range(frames):
            alpha = i / max(1, frames - 1)
            frame = Image.blend(img_a, img_b, alpha)
            all_frames.append(frame.convert("P"))

        # optional: hold on result for a bit
        for _ in range(3):
            all_frames.append(all_frames[-1])

        all_frames[0].save(
            gif_out,
            save_all=True,
            append_images=all_frames[1:],
            duration=duration_ms,
            loop=0,
            disposal=2,
        )

        print(f"🎞 Animated diff GIF written → {gif_out}")
# ultimate_pipeline/visualization/animated_diff.py

import os
from PIL import Image


class AnimatedDiff:
    """
    Build an animated GIF showing a smooth transition between
    two map previews (e.g. before/after continuity).
    """

    @staticmethod
    def run(before_png, after_png, gif_out, frames=12, duration_ms=150):
        if not os.path.exists(before_png):
            print(f"❌ before_png missing: {before_png}")
            return
        if not os.path.exists(after_png):
            print(f"❌ after_png missing: {after_png}")
            return

        img_a = Image.open(before_png).convert("RGBA")
        img_b = Image.open(after_png).convert("RGBA")

        # resize to match
        if img_a.size != img_b.size:
            img_b = img_b.resize(img_a.size, Image.BILINEAR)

        all_frames = []

        # fade A → B
        for i in range(frames):
            alpha = i / max(1, frames - 1)
            frame = Image.blend(img_a, img_b, alpha)
            all_frames.append(frame.convert("P"))

        # optional: hold on result for a bit
        for _ in range(3):
            all_frames.append(all_frames[-1])

        all_frames[0].save(
            gif_out,
            save_all=True,
            append_images=all_frames[1:],
            duration=duration_ms,
            loop=0,
            disposal=2,
        )

        print(f"🎞 Animated diff GIF written → {gif_out}")
