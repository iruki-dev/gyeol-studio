"""Start check (시작 검사): range, singing back notes, intervals, a short melody, and hearing pitch differences.

The browser plays the stimuli and records each answer; this module turns the recordings into sung pitches with
``gyeol.api.analyze`` and scores them with ``gyeol.coach.onboarding.score_onboarding`` (SSAP / SPB style:
production accuracy, precision, perception, routing) and ``gyeol.coach.health.VoiceRange.from_samples``.
The summary is plain Korean from the app's strings; band names are never shown as labels for people.
"""

from __future__ import annotations

import numpy as np

from . import audio
from .coaching import strings

TASKS = ("glide", "comfortable", "match", "interval", "melody")
CONF = 0.5


def cents_of_hz(f: float) -> float:
    return 1200.0 * np.log2(f / 440.0)


def sung_pitch(path, skip_s: float = 0.25, keep=None) -> tuple[np.ndarray, list[tuple[int, int]], float]:
    """Confident f0 (cents re A4, NaN elsewhere), note spans (frames) and hop seconds of one recording.
    ``keep(doc_json)`` receives the analysis document (gyeol.representation) for storage."""
    from gyeol import api

    x, sr = audio.read(path)
    r = api.analyze(x, sr, separation="off")
    if not r.usable:
        return np.array([]), [], 0.01
    rep = r.value
    if keep is not None:
        keep(api.to_json(rep))
    c = rep.curves["f0_cents"]
    v = np.where(c.confidence >= CONF, c.values, np.nan)
    hop = rep.grid.hop_seconds
    v[: int(skip_s / hop)] = np.nan
    return v, [tuple(n) for n in rep.meta.get("notes", [])], hop


def _median(v: np.ndarray) -> float:
    v = v[np.isfinite(v)]
    return float(np.median(v)) if v.size >= 5 else float("nan")


def _segments(v: np.ndarray, notes: list[tuple[int, int]], k: int) -> list[float]:
    """k sung pitches: from gyeol's note spans when it found k notes, else k equal parts of the voiced region."""
    good = [(s, e) for s, e in notes if np.isfinite(v[s:e]).sum() >= 3]
    if len(good) == k:
        return [_median(v[s:e]) if np.isfinite(v[s:e]).sum() >= 5 else float(np.nanmedian(v[s:e])) for s, e in good]
    idx = np.flatnonzero(np.isfinite(v))
    if idx.size < 5 * k:
        return [float("nan")] * k
    parts = np.array_split(np.arange(idx[0], idx[-1] + 1), k)
    out = []
    for p in parts:
        seg = v[p]
        mid = seg[len(seg) // 5: len(seg) - len(seg) // 5] if len(seg) >= 10 else seg  # skip the glides between notes
        out.append(_median(mid) if np.isfinite(mid).sum() >= 5 else float("nan"))
    return out


def score(check_dir, trials: list[dict], discrimination: list[dict], progress=lambda f, m: None, keep=None) -> dict:
    from gyeol.coach import DiscriminationTrial, IntervalTrial, MelodyTrial, PitchMatchTrial, VoiceRange, score_onboarding

    glide, comfy = [], []
    pm, iv, mel = [], [], []
    measured = []
    for i, t in enumerate(trials):
        progress(i / max(1, len(trials)), f"검사 녹음 {i + 1}/{len(trials)} 분석하는 중")
        v, notes, _hop = sung_pitch(check_dir / t["file"], keep=keep)
        task = t["task"]
        m = {"task": task, "file": t["file"]}
        if task == "glide":
            glide.append(v[np.isfinite(v)])
        elif task == "comfortable":
            comfy.append(v[np.isfinite(v)])
        elif task == "match":
            sung = _median(v)
            pm.append(PitchMatchTrial(float(t["targets"][0]), sung))
            m["sung"] = [sung]
        elif task == "interval":
            a, b = _segments(v, notes, 2)
            iv.append(IntervalTrial(float(t["targets"][1] - t["targets"][0]), a, b))
            m["sung"] = [a, b]
        elif task == "melody":
            k = len(t["targets"])
            sung = _segments(v, notes, k)
            mel.append(MelodyTrial(tuple(float(x) for x in t["targets"]), tuple(sung)))
            m["sung"] = sung
        m["targets"] = t.get("targets")
        measured.append(m)
    vr, vr_reason = None, None
    try:
        g = np.concatenate(glide) if glide else np.array([])
        c = np.concatenate(comfy) if comfy else np.array([])
        vr = VoiceRange.from_samples(np.concatenate([g, c]), c, source="start check")
    except ValueError as exc:
        vr_reason = str(exc)
    disc = [DiscriminationTrial(float(d["delta"]), bool(d["correct"])) for d in discrimination]
    prof = score_onboarding(pm, iv, mel, disc, voice_range=vr)
    profile = {
        "production_mae_cents": prof.production_mae_cents, "precision_sd_cents": prof.precision_sd_cents,
        "perception_threshold_cents": prof.perception_threshold_cents, "production_band": prof.production_band,
        "precision_band": prof.precision_band, "perception_band": prof.perception_band, "routes": prof.routes,
        "per_task_mae": prof.per_task_mae, "status": prof.status,
        "voice_range": None if vr is None else {"low_cents": vr.low_cents, "high_cents": vr.high_cents, "tess_low_cents": vr.tess_low_cents,
                                                "tess_high_cents": vr.tess_high_cents, "source": vr.source},
        "voice_range_reason": vr_reason,
    }
    profile = _jsonable(profile)
    return {"profile": profile, "summary": summarize(profile), "measured": _jsonable(measured)}


def _jsonable(x):
    """Plain JSON values; non-finite numbers become null."""
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    if isinstance(x, np.integer):
        return int(x)
    return x


NOTE_KO = ["도", "도#", "레", "레#", "미", "파", "파#", "솔", "솔#", "라", "라#", "시"]


def note_ko(cents: float) -> str:
    midi = int(round(69 + cents / 100))
    return f"{NOTE_KO[midi % 12]}{midi // 12 - 1}"


def summarize(p: dict) -> list[dict]:
    """Plain-language lines: [{title, text}]."""
    s = strings()["onboarding"]
    out = []
    vr = p.get("voice_range")
    if vr:
        out.append({"title": "음역", "text": f"편하게 부를 수 있는 음역은 {note_ko(vr['tess_low_cents'])}부터 {note_ko(vr['tess_high_cents'])}까지예요. "
                                            f"소리를 낼 수 있는 전체 음역은 {note_ko(vr['low_cents'])}~{note_ko(vr['high_cents'])}쯤이에요."})
    else:
        out.append({"title": "음역", "text": "음역을 재기에는 녹음이 모자랐어요. 미끄러지듯 올라가는 '아~'를 조금 더 길게 불러 주세요."})
    for key, title in (("production", "음 따라 부르기"), ("precision", "같은 음 다시 부르기"), ("perception", "음 구별 듣기")):
        band = p.get(f"{key}_band")
        text = s[key][band] if band else s["not_enough"]
        if key == "production" and p.get("production_mae_cents") is not None:
            text += f" (평균 {p['production_mae_cents']:.0f}센트 차이 — 100센트가 반음 하나예요)"
        if key == "perception" and p.get("perception_threshold_cents") is not None:
            text += f" (약 {p['perception_threshold_cents']:.0f}센트 차이까지 구별했어요)"
        out.append({"title": title, "text": text})
    for r in p.get("routes", []):
        if r in s["routes"]:
            out.append({"title": "추천 연습", "text": s["routes"][r]})
    return out
