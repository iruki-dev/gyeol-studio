"""Test fixtures: an app with its own config and data folders, and synthetic singing from gyeol.synth."""

from __future__ import annotations

import io
import time

import numpy as np
import pytest

SR = 44100


@pytest.fixture()
def env(tmp_path, monkeypatch):
    cfg, data = tmp_path / "config", tmp_path / "data"
    monkeypatch.setenv("GYEOL_STUDIO_CONFIG", str(cfg))
    from gyeol_studio.settings import Settings, save_settings

    s = Settings(data_dir=str(data), lan=False)
    s.advanced.audibility = False  # keeps the tests fast; audibility is covered by the e2e run
    save_settings(s)
    return s


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient

    from gyeol_studio.server import create_app

    app = create_app(env, start_workers=True)
    with TestClient(app) as c:
        yield c
    app.state.studio.workers.stop()


def wav_bytes(x: np.ndarray, sr: int = SR) -> bytes:
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, np.asarray(x, np.float32), sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def melody_audio(detune=(0, 0, 0, 0, 0, 0), shifts=(0, 0, 0, 0, 0, 0), seed=0, transpose=0.0) -> np.ndarray:
    from gyeol import api

    base = [(262, "a", "s"), (294, "a", None), (330, "e", "h"), (349, "o", None), (392, "e", "k"), (330, "e", "t")]
    notes = [api.SynthNote(f * 2 ** (d / 1200), 0.6, gap_after=0.12, vowel=v, consonant=c, onset_shift_s=s)
             for (f, v, c), d, s in zip(base, detune, shifts)]
    return api.melody(notes, sr=SR, seed=seed, transpose_cents=transpose).audio


def wait_job(client, headers, pred, timeout=120.0, every=0.5):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        last = pred()
        if last:
            return last
        time.sleep(every)
    jobs = client.get("/api/jobs?mine=false", headers=headers).json()
    raise AssertionError(f"timed out; jobs: {jobs}")
