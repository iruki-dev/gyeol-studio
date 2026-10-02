"""Audio file helpers on top of ``gyeol.api.load_audio`` / ``save_audio``: slices, peaks, take trimming."""

from __future__ import annotations

from pathlib import Path

import numpy as np

MAX_SONG_S = 15 * 60


def read(path: str | Path) -> tuple[np.ndarray, int]:
    from gyeol import api

    x, sr = api.load_audio(path)
    x = np.asarray(x, float)
    if x.ndim > 1:  # load_audio returns mono; keep the guard for other inputs
        x = x.mean(axis=1)
    return x, int(sr)


def write(path: str | Path, x: np.ndarray, sr: int) -> Path:
    from gyeol import api

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp" + path.suffix)
    api.save_audio(tmp, np.clip(np.asarray(x, float), -1.0, 1.0), int(sr))
    tmp.replace(path)
    return path


def segment(x: np.ndarray, sr: int, t0: float, t1: float) -> np.ndarray:
    """Samples [t0, t1) (seconds); zero-padded where the range runs past either end."""
    a, b = int(round(t0 * sr)), int(round(t1 * sr))
    out = np.zeros(max(0, b - a))
    lo, hi = max(a, 0), min(b, len(x))
    if hi > lo:
        out[lo - a:hi - a] = x[lo:hi]
    return out


def resample(x: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    if sr_from == sr_to:
        return x
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(int(sr_from), int(sr_to))
    return resample_poly(x, sr_to // g, sr_from // g)


def peaks(x: np.ndarray, n: int = 1000) -> list[list[float]]:
    """[min, max] per bucket for drawing a waveform."""
    if len(x) == 0:
        return []
    n = max(1, min(n, len(x)))
    edges = np.linspace(0, len(x), n + 1).astype(int)
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        seg = x[a:max(b, a + 1)]
        out.append([round(float(seg.min()), 4), round(float(seg.max()), 4)])
    return out


def peaks_payload(x: np.ndarray, sr: int, n: int = 1000) -> dict:
    return {"duration_s": len(x) / sr, "peaks": peaks(x, n)}


def trim_take(raw: np.ndarray, sr: int, phrase_offset_s: float, phrase_dur_s: float) -> tuple[np.ndarray, float]:
    """Cut the phrase out of a raw sing-along recording.

    ``phrase_offset_s`` is where the phrase starts in ``raw`` after latency compensation.
    Returns the take (exactly the phrase's length, zero-padded at the end if the recording stopped early)
    and the fraction of the phrase that was actually recorded.
    """
    take = segment(raw, sr, phrase_offset_s, phrase_offset_s + phrase_dur_s)
    a = int(round(phrase_offset_s * sr))
    covered = max(0, min(len(raw), a + len(take)) - max(a, 0)) / max(1, len(take))
    return take, covered


def rms_db(x: np.ndarray) -> float:
    r = float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0
    return 20 * np.log10(max(r, 1e-9))
