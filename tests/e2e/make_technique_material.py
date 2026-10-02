"""Real-voice technique pairs for the phase-4 e2e, from VocalSet (CC BY 4.0, https://zenodo.org/records/1442513).

    python tests/e2e/make_technique_material.py <out dir>

Only the needed files are read out of the 2.6 GB zip (HTTP range requests via ``remotezip``):
female1–6 sing the same arpeggio plainly ("straight") and with a technique (breathy, belt, vocal fry); female7's
plain arpeggio is the song. Writes ``vs_<singer>_<technique>_<vowel>.wav`` (mono) and ``technique_plan.json``
with where the sung part starts in each file, so the e2e can line takes up with the phrase.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np

URL = "https://zenodo.org/api/records/1442513/files/VocalSet11.zip/content"
SINGERS = [f"female{i}" for i in range(1, 7)]
# (contrast in the app, plain file, technique file) — vowel-matched pairs
PAIRS = [("breathy", ("straight", "a"), ("breathy", "a")), ("breathy", ("straight", "o"), ("breathy", "o")),
         ("pressed_belt", ("straight", "e"), ("belt", "e")), ("fry", ("straight", "i"), ("vocal_fry", "i"))]
SONG = ("female7", "straight", "a")


def onset(x: np.ndarray, sr: int) -> float:
    """First 10 ms frame louder than 5 % of the loudest one."""
    hop = sr // 100
    rms = np.sqrt(np.convolve(x**2, np.ones(hop) / hop, mode="valid")[::hop])
    return float(np.argmax(rms > rms.max() * 0.05) * 0.01)


def main(out: str) -> None:
    import soundfile as sf
    from remotezip import RemoteZip

    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    plan = {"song": None, "singers": {}}
    with RemoteZip(URL) as z:
        names = [n for n in z.namelist() if "/arpeggios/" in n and n.endswith(".wav") and not n.startswith("__MACOSX")]

        def fetch(singer: str, tech: str, vowel: str) -> dict:
            src = next(n for n in names if f"/{singer}/arpeggios/{tech}/" in n and n.endswith(f"_{vowel}.wav"))
            x, sr = sf.read(io.BytesIO(z.read(src)))
            x = x.mean(axis=1) if x.ndim > 1 else x
            name = f"vs_{singer}_{tech}_{vowel}.wav"
            sf.write(d / name, x.astype(np.float32), sr)
            return {"file": name, "source": src, "onset_s": onset(x, sr), "dur_s": len(x) / sr}

        plan["song"] = fetch(*SONG)
        for s in SINGERS:
            plan["singers"][s] = [{"contrast": c, "off": fetch(s, *off), "on": fetch(s, *on)} for c, off, on in PAIRS]
            print(s, "ok")
    (d / "technique_plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    print(f"wrote {d}")


if __name__ == "__main__":
    main(sys.argv[1])
