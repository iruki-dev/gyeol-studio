"""Practice history: per-phrase change by category, daily singing time, fatigue signs (gyeol.coach.health)."""

from __future__ import annotations

import datetime as dt
import json

from fastapi import APIRouter, Request

from .. import coaching, db
from ..deps import conn, current_user, get_or_404
from ..tasks.takes import day_key, fatigue

router = APIRouter(prefix="/api/history")

# per category: the attribute whose |magnitude| tracks progress, and its unit
TRACKS = {
    "pitch": ("intonation_offset", "센트", "음 높이 차이"),
    "rhythm": ("onset_timing", "ms", "들어가는 타이밍 차이"),
    "dynamics": ("loudness", "dB", "음 세기 차이"),
}


def _metrics(exp: dict) -> dict:
    out = {}
    for cat, (attr, _unit, _label) in TRACKS.items():
        vals = [abs(it["magnitude"]) for it in exp.get("items", []) if it["attribute"] == attr and (it.get("confidence") or 0) >= 0.5
                and it.get("magnitude") is not None]
        out[cat] = round(sum(vals) / len(vals), 1) if vals else None
    return out


@router.get("/phrases")
def practiced_phrases(request: Request):
    c = conn(request)
    user = current_user(request)
    rs = c.execute("SELECT p.id, p.name, p.lyrics, s.title AS song_title, COUNT(t.id) n, MAX(t.created_at) last FROM takes t "
                   "JOIN phrases p ON p.id=t.phrase_id JOIN songs s ON s.id=p.song_id WHERE t.user_id=? GROUP BY p.id ORDER BY last DESC",
                   (user["id"],)).fetchall()
    return {"phrases": [dict(r) for r in rs]}


@router.get("/phrase/{pid}")
def phrase_history(request: Request, pid: str):
    c = conn(request)
    user = current_user(request)
    get_or_404(c, "phrases", pid)
    rs = c.execute("SELECT t.id, t.created_at, t.session_key, f.explanation_id, f.coaching FROM takes t LEFT JOIN feedback f ON f.take_id=t.id "
                   "WHERE t.phrase_id=? AND t.user_id=? AND t.status='ready' ORDER BY t.created_at", (pid, user["id"])).fetchall()
    points = []
    for r in rs:
        m = {}
        primary = None
        if r["explanation_id"]:
            m = _metrics(json.loads(db.load_analysis_json(c, r["explanation_id"]) or "{}"))
        if r["coaching"]:
            p = json.loads(r["coaching"]).get("primary")
            primary = p and {"category": p["category"], "label": p["category_label"], "text": p["text"]}
        points.append({"take_id": r["id"], "t": r["created_at"], "session": r["session_key"], "metrics": m, "primary": primary})
    return {"points": points, "tracks": {k: {"unit": u, "label": label} for k, (_a, u, label) in TRACKS.items()}}


@router.get("/wellbeing")
def wellbeing(request: Request, days: int = 14):
    from gyeol.coach.health import load_norms

    c = conn(request)
    user = current_user(request)
    since = db.now() - days * 86400
    rs = c.execute("SELECT created_at, session_key, voiced_s, metrics FROM takes WHERE user_id=? AND status='ready' AND created_at>=? "
                   "ORDER BY created_at", (user["id"], since)).fetchall()
    by_day: dict[str, dict] = {}
    for r in rs:
        d = by_day.setdefault(day_key(r["created_at"]), {"voiced_s": 0.0, "takes": 0})
        d["voiced_s"] += r["voiced_s"] or 0.0
        d["takes"] += 1
    today = dt.date.today()
    series = []
    for i in range(days - 1, -1, -1):
        k = (today - dt.timedelta(days=i)).strftime("%Y-%m-%d")
        series.append({"day": k, **by_day.get(k, {"voiced_s": 0.0, "takes": 0})})
    last = rs[-1] if rs else None
    session_s, fat, metrics = 0.0, [], []
    if last is not None and db.now() - last["created_at"] < 3 * 3600:
        sess = [r for r in rs if r["session_key"] == last["session_key"]]
        session_s = sum(r["voiced_s"] or 0.0 for r in sess)
        metrics = [json.loads(r["metrics"]) for r in sess if r["metrics"]]
        fat = fatigue(metrics) if metrics else []
    h = load_norms()["health"]
    notices = coaching.health_notices(session_s=session_s, day_s=series[-1]["voiced_s"], fatigue=fat, phrase_check=None)
    return {"days": series, "today_s": series[-1]["voiced_s"], "session_s": session_s, "session_takes": len(metrics),
            "fatigue": fat, "fatigue_min_attempts": h["fatigue_min_attempts"], "notices": notices,
            "norms": {"daily_warn_s": h["daily_phonation_warn_s"], "session_warn_s": h["session_phonation_warn_s"]},
            "referral": coaching.strings()["health"]["referral"]}
