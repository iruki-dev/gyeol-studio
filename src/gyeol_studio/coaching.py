"""What to show after a take: one main point, at most two more, and the evidence.

Order and filtering use gyeol's coaching policy:

* an item is shown only if it passes its fitted display threshold
  (``ThresholdSet.passes``) and the beginner health restrictions
  (``gyeol.coach.health.restricted_for_level``);
* the remaining items are ordered by ``gyeol.coach.priority.rank``
  (reliability × audibility, category tie order);
* the first is the main point, the next two (at most) are expandable extras.

Items without any fitted threshold are hidden by default.  With the advanced
setting "검증 기준이 없는 항목도 보기" they are ranked separately after the
verified ones and marked "참고용".

The evidence view (``evidence``) puts the take's pitch curve and the target's
(mapped through the explanation's time warp τ and transposition) on the take's
time axis, with the lyric syllables and each item's spans.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

import numpy as np

CATEGORY_LABEL = {"pitch": "음정", "rhythm": "박자", "ornament": "꾸밈음", "dynamics": "강약", "phonation": "발성", "diction": "발음"}
SELF_ASSESSMENT = [("pitch", "음정"), ("rhythm", "박자"), ("dynamics", "강약"), ("ornament", "꾸밈음"), ("phonation", "발성"),
                   ("diction", "발음"), ("nothing", "잘 모르겠어요")]


@lru_cache(maxsize=1)
def strings() -> dict:
    return json.loads(resources.files("gyeol_studio").joinpath("resources/strings.ko.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def thresholds():
    from gyeol.coach import ThresholdSet

    with resources.as_file(resources.files("gyeol_studio").joinpath("resources/thresholds.json")) as p:
        return ThresholdSet.from_json(p)


@lru_cache(maxsize=1)
def practice_map():
    from gyeol.coach import PracticeMap

    return PracticeMap.load(lang="ko")


def key_str(key: tuple) -> str:
    c, a, n = key
    return f"{c}:{a}:{int(n)}"


def key_tuple(s: str) -> tuple:
    c, a, n = s.split(":")
    return (c, a, int(n))


def _item_view(it, rank_score: float | None, basis: str, grid, *, experimental: bool, level: str) -> dict:
    from gyeol import api

    cons = api.load_strings("ko")["consistency"].get(it.consistency.value, "")
    ex = practice_map().for_item(it, level)
    spans = [[round(float(grid.time_of(s.start)), 3), round(float(grid.time_of(s.end)), 3)] for s in it.spans]
    return {
        "key": key_str(it.key),
        "category": it.category,
        "category_label": CATEGORY_LABEL.get(it.category, it.category),
        "attribute": it.attribute,
        "text": api.item_text(it, "ko"),
        "magnitude": float(it.magnitude),
        "unit": it.unit,
        "confidence": round(float(it.confidence), 3),
        "audibility": None if it.audibility is None else round(float(it.audibility), 4),
        "consistency": it.consistency.value,
        "consistency_text": cons,
        "tentative": it.category == "phonation" or bool(it.detail.get("tentative")),
        "experimental": experimental,
        "score": None if rank_score is None else round(float(rank_score), 5),
        "basis": basis,
        "spans": spans,
        "practice": [{"title": e.title, "minutes": e.minutes, "instructions": e.instructions} for e in ex[:1]],
    }


def select(exp, *, level: str = "beginner", show_unverified: bool = False, voice_range=None, target_note_cents=None,
           n_secondary: int = 2) -> dict:
    """Filter and rank an explanation's items → the coaching document stored with the take's feedback."""
    from gyeol import api
    from gyeol.coach import check_phrase, rank, restricted_for_level

    ts = thresholds()
    shift = 0.0
    phrase = None
    if voice_range is not None and target_note_cents:
        phrase = check_phrase(target_note_cents, voice_range)
        shift = phrase.octave_shift_cents
    verified, unverified, withheld = [], [], {}
    for it in exp.items:
        ok, why = ts.passes(it)
        if ok:
            r = restricted_for_level(it, level, voice_range, target_note_cents, shift)
            if r is not None:
                ok, why = False, "beginner_restricted"
        if ok:
            verified.append(it)
        elif why == "no_threshold" and show_unverified and it.confidence >= 0.5:
            unverified.append(it)
        else:
            withheld[why] = withheld.get(why, 0) + 1
    ranked = [(r, False) for r in rank(verified, ts)] + [(r, True) for r in rank(unverified, ts)]
    views = [_item_view(r.item, r.score, r.basis, exp.grid, experimental=x, level=level) for r, x in ranked]
    notes = api.explanation_notes(exp, "ko")
    s = strings()
    hidden = sum(withheld.values())
    return {
        "primary": views[0] if views else None,
        "secondary": views[1:1 + n_secondary],
        "more_available": max(0, len(views) - 1 - n_secondary),
        "notes": notes,
        "withheld": withheld,
        "hidden_count": hidden,
        "none_text": s["feedback"]["none"],
        "thresholds": {"synthetic": bool(ts.provenance.get("synthetic")), "data": ts.provenance.get("data", "")},
        "phrase_check": None if phrase is None else {"status": phrase.status, "transpose_semitones": phrase.transpose_semitones,
                                                     "octave_shift_cents": phrase.octave_shift_cents},
        "n_takes": exp.n_takes,
        "level": level,
    }


def self_assessment_result(noticed: list[str], coaching: dict) -> dict:
    s = strings()["self_assessment"]
    n = set(noticed)
    primary = coaching.get("primary")
    if not n or n <= {"nothing"}:
        match = "nothing"
    elif primary is None:
        match = "no_items"
    else:
        match = "matched" if primary["category"] in n else "missed"
    return {"noticed": sorted(n), "match": match, "message": s[match]}


def health_notices(*, session_s: float, day_s: float, fatigue: list[str], phrase_check: dict | None) -> list[dict]:
    """Health notices (gyeol.coach.health measures; wording from the app's strings)."""
    from gyeol.coach import phonation_warnings

    h = strings()["health"]
    out = [{"id": w, "text": h[w], "kind": "rest"} for w in phonation_warnings(session_s, day_s)]
    out += [{"id": f, "text": h[f], "kind": "rest"} for f in fatigue if f in h]
    if phrase_check:
        st = phrase_check["status"]
        if st in ("above_tessitura", "below_tessitura", "out_of_range"):
            out.append({"id": st, "text": h[st], "kind": "range"})
        k = phrase_check.get("transpose_semitones") or 0
        if k:
            out.append({"id": "transpose", "text": h["transpose"].format(direction=h["transpose_up" if k > 0 else "transpose_down"],
                                                                     semitones=abs(k)), "kind": "range"})
    return out


# ---------------------------------------------------------------- evidence (pitch curves + syllables)


def _downsample(n: int, max_points: int) -> np.ndarray:
    step = max(1, int(np.ceil(n / max_points)))
    return np.arange(0, n, step)


def _clean(v: np.ndarray, digits: int = 1) -> list:
    return [None if not np.isfinite(x) else round(float(x), digits) for x in v]


def evidence(exp, take_rep, target_rep, max_points: int = 700) -> dict:
    """Pitch curves (cents re A4) and loudness on the take's time axis, with syllables and item spans."""
    grid = take_rep.grid
    n = grid.n_frames
    times = np.array([grid.time_of(i) for i in range(n)], float)
    f0 = take_rep.curves["f0_cents"]
    user = np.where(f0.confidence >= 0.3, f0.values, np.nan)
    warp = np.asarray(exp.warp, float)
    if len(warp) != n:  # explanation grid is the take's grid; guard against a mismatch anyway
        warp = np.interp(np.linspace(0, len(warp) - 1, n), np.arange(len(warp)), warp)
    tf0 = target_rep.curves["f0_cents"]
    tvals = np.where(tf0.confidence >= 0.3, tf0.values, np.nan)
    m = len(tvals)
    idx = np.clip(np.rint(warp).astype(int), 0, m - 1)
    tgt = tvals[idx]
    tgt[(warp < -0.5) | (warp > m - 0.5)] = np.nan
    trans = exp.transposition_cents
    if trans is None:  # octave-invariant comparison: draw the target in the take's octave for readability
        both = np.isfinite(user) & np.isfinite(tgt)
        trans = 1200.0 * round(float(np.median(user[both] - tgt[both])) / 1200.0) if both.sum() > 5 else 0.0
    tgt_disp = tgt + float(trans)

    def loud(rep):
        c = rep.curves.get("loudness") if hasattr(rep.curves, "get") else None
        return None if c is None else np.where(c.confidence > 0, c.values, np.nan)

    lu, lt = loud(take_rep), loud(target_rep)
    sel = _downsample(n, max_points)
    out = {
        "times": _clean(times[sel], 3),
        "user_cents": _clean(user[sel]),
        "target_cents": _clean(tgt_disp[sel]),
        "transposition_cents": float(trans),
        "duration_s": float(times[-1] + grid.hop_seconds) if n else 0.0,
        # analyze() advanced the take by this much (latency refined against the guide); demos are on that clock
        "take_offset_s": float((take_rep.meta.get("latency") or {}).get("offset_s") or 0.0),
    }
    if lu is not None and lt is not None:
        out["user_loudness"] = _clean(lu[sel])
        out["target_loudness"] = _clean(lt[idx][sel])
    syl = []
    for s, e, text in target_rep.meta.get("syllables", []) or []:
        frames = np.flatnonzero((warp >= s) & (warp < e))
        if frames.size:
            syl.append({"start": round(float(times[frames[0]]), 3), "end": round(float(times[frames[-1]] + grid.hop_seconds), 3), "text": text})
    out["syllables"] = syl
    out["cannot_judge"] = [[round(float(grid.time_of(s.start)), 3), round(float(grid.time_of(s.end)), 3), s.reason] for s in exp.cannot_judge]
    return out
