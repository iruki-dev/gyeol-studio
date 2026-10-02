"""Sung-note clips for the start-check e2e (synthetic singing from gyeol.synth; no people).

    python tests/e2e/make_check_material.py <out dir>

note_<cents>.wav   one sung "a" at <cents> re A4, every 25 cents from -2400 to +600 (0.9 s)
glide_up.wav / glide_down.wav   C3 → C5 / C5 → C3 in semitone steps
comfortable.wav    도레미파솔파미레도 around A3
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from gyeol import api

SR = 44100


def sing(cents, dur, seed=0, vib=0.0):
    notes = [api.SynthNote(440.0 * 2 ** (c / 1200), dur, gap_after=0.03, vowel="a", vibrato_rate=5.5 if vib else 0, vibrato_extent_cents=vib)
             for c in cents]
    return api.melody(notes, sr=SR, seed=seed).audio


def main(out: str) -> None:
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    for c in range(-2400, 601, 25):
        api.save_audio(d / f"note_{c}.wav", sing([c], 0.9, seed=c % 97, vib=25), SR)
    up = list(range(-2100, 301, 100))
    api.save_audio(d / "glide_up.wav", np.r_[np.zeros(SR // 4), sing(up, 0.2)], SR)
    api.save_audio(d / "glide_down.wav", np.r_[np.zeros(SR // 4), sing(up[::-1], 0.2, seed=1)], SR)
    api.save_audio(d / "comfortable.wav", np.r_[np.zeros(SR // 4), sing([-1200, -1000, -800, -700, -500, -700, -800, -1000, -1200], 0.6, seed=2, vib=20)], SR)
    print(f"wrote {d}")


if __name__ == "__main__":
    main(sys.argv[1])
