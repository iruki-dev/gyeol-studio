"""Copy screenshots into docs/screenshots/<phase>/ as palette PNGs (much smaller, text stays crisp).

    python scripts/optimize_shots.py <src dir> docs/screenshots/phase-1 [names...]
"""

import sys
from pathlib import Path

from PIL import Image

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
names = sys.argv[3:]
dst.mkdir(parents=True, exist_ok=True)
for p in sorted(src.glob("*.png")):
    if names and p.stem not in names:
        continue
    im = Image.open(p).convert("RGB")
    if im.width > 1400:
        im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)  # phone shots are 2x
    im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(dst / p.name, optimize=True)
    print(f"{p.name}: {p.stat().st_size // 1024} → {(dst / p.name).stat().st_size // 1024} KB")
