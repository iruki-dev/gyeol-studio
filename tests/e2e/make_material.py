"""E2E material from CSD kr003a (곰 세마리; real Korean singing, CC BY-NC-SA 4.0 — local testing only, never committed).

    python tests/e2e/make_material.py <CSD>/korean <out dir>

gom3_song.wav       the first 24 s of the vocal over an accompaniment synthesized from the note annotation
gom3_take_v2.wav    the same lyric line from the second verse (a second real performance), aligned at its first onset
gom3_take_flat.wav  gom3_take_v2 pitch-shifted 35 cents down (librosa; timing unchanged)
gom3_phrase.txt     the phrase (start, end) on the song timeline
"""

from __future__ import annotations

import csv
import sys

import librosa
import numpy as np
import soundfile as sf

LINE = ["g_o_m", "s_e", "m_a", "r_i"]  # 곰 세마리…
N_SYLLABLES = 19  # 곰 세마리가 한 집에 있어 아빠곰 엄마곰 애기곰
SONG_S = 24.0


def accompaniment(rows, n: int, sr: int) -> np.ndarray:
    acc = np.zeros(n)
    rng = np.random.default_rng(0)

    def tone(f, a, b, amp):
        i0, i1 = int(a * sr), min(n, int(b * sr))
        if i1 <= i0:
            return
        tt = np.arange(i1 - i0) / sr
        env = np.minimum(1, tt / 0.01) * np.exp(-tt * 1.2)
        for k, w in ((1, 1.0), (2, 0.35), (3, 0.12)):
            acc[i0:i1] += amp * w * env * np.sin(2 * np.pi * f * k * tt)

    beat = 0.5217
    bar = 4 * beat
    for b0 in np.arange(rows[0][0] - bar, n / sr, bar):
        ps = [p for a, _, p, _ in rows if b0 <= a < b0 + bar] or [59]
        tone(440 * 2 ** ((min(ps) - 24 - 69) / 12), b0, b0 + bar, 0.5)
        for p in sorted(set(ps))[:3]:
            tone(440 * 2 ** ((p - 12 - 69) / 12), b0, b0 + bar, 0.12)
    for bt in np.arange(rows[0][0], n / sr, beat):
        i = int(bt * sr)
        m = min(int(0.03 * sr), n - i)
        acc[i:i + m] += 0.12 * rng.standard_normal(m) * np.exp(-np.arange(m) / (0.004 * sr))
    return acc * 0.35 / np.max(np.abs(acc))


def main(src: str, out: str) -> None:
    x, sr = sf.read(f"{src}/wav/kr003a.wav")
    x = x.mean(1)
    rows = [(float(a), float(b), int(p), s) for a, b, p, s in list(csv.reader(open(f"{src}/csv/kr003a.csv", encoding="utf-8")))[1:]]
    sylls = [r[3] for r in rows]
    occ = [i for i in range(len(sylls) - 3) if sylls[i:i + 4] == LINE]
    n = int(SONG_S * sr)
    mix = x[:n] + accompaniment(rows, n, sr)
    mix /= 1.1 * np.max(np.abs(mix))
    sf.write(f"{out}/gom3_song.wav", np.stack([mix, mix], 1), sr)
    p0, p1 = rows[occ[0]][0] - 0.15, rows[occ[0] + N_SYLLABLES - 1][1] + 0.35
    s2 = rows[occ[1]][0] - 0.15
    take = x[int(s2 * sr): int((s2 + (p1 - p0)) * sr)]
    sf.write(f"{out}/gom3_take_v2.wav", take, sr)
    sf.write(f"{out}/gom3_take_flat.wav", librosa.effects.pitch_shift(take.astype(np.float32), sr=sr, n_steps=-0.35), sr)
    with open(f"{out}/gom3_phrase.txt", "w") as fh:
        fh.write(f"{p0:.3f} {p1:.3f}\n")
    print("phrase", round(p0, 3), round(p1, 3), "second verse at", rows[occ[1]][0])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
