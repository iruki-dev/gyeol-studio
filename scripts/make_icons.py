"""Draw the app icon (the same mark as web/img/icon.svg) and write packaging/icons/icon.{png,ico,icns}.

    pip install pillow && python scripts/make_icons.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "packaging" / "icons"


def wave(img, size, y0, amp, width, color):
    """A thick sine stroke: discs stamped along the path into a mask (clean joins), composited with the colour's alpha."""
    mask = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(mask)
    r = width / 2
    for i in range(0, 2001):
        x = size * (0.19 + 0.62 * i / 2000)
        y = y0 + amp * math.sin(2 * math.pi * 1.5 * i / 2000)
        d.ellipse((x - r, y - r, x + r, y + r), fill=color[3])
    layer = Image.new("RGBA", img.size, color[:3] + (255,))
    img.paste(layer, (0, 0), mask)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s = 1024
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.25), fill=(201, 79, 53, 255))
    wave(img, s, s * 0.42, s * 0.05, int(s * 0.055), (255, 255, 255, 140))
    wave(img, s, s * 0.6, s * 0.08, int(s * 0.08), (255, 255, 255, 255))
    img.save(OUT / "icon.png")
    img.save(OUT / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(OUT / "icon.icns")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
