"""Start check: create a session, upload each trial's recording, finish with the listening answers, read the result."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, File, Form, Request, UploadFile

from .. import audio, checks, db, jobs
from ..coaching import health_notices
from ..deps import ApiError, conn, current_user, get_or_404, state

router = APIRouter(prefix="/api")


def _view(ch: dict) -> dict:
    out = {k: ch[k] for k in ("id", "user_id", "created_at", "status")}
    out["profile"] = json.loads(ch["profile"]) if ch.get("profile") else None
    out["summary"] = json.loads(ch["summary"]) if ch.get("summary") else None
    t = json.loads(ch["trials"]) if isinstance(ch["trials"], str) else ch["trials"]
    out["n_recordings"] = len(t.get("recordings", []))
    out["n_discrimination"] = len(t.get("discrimination", []))
    return out


@router.post("/checks")
def start_check(request: Request):
    c = conn(request)
    user = current_user(request)
    if not user["consent_analysis"]:
        raise ApiError("consent_required", 403)
    cid = db.new_id()
    c.execute("INSERT INTO checks(id, user_id, created_at, status, trials) VALUES(?,?,?,?,?)",
              (cid, user["id"], db.now(), "recording", db.dumps({"recordings": [], "discrimination": []})))
    return _view(get_or_404(c, "checks", cid))


@router.post("/checks/{cid}/recordings")
def add_recording(request: Request, cid: str, file: UploadFile = File(...), meta: str = Form("{}")):
    st, c = state(request), conn(request)
    user = current_user(request)
    ch = get_or_404(c, "checks", cid)
    if ch["user_id"] != user["id"] or ch["status"] != "recording":
        raise ApiError("not_found", 404)
    m = json.loads(meta or "{}")
    task = m.get("task")
    if task not in checks.TASKS:
        raise ApiError("bad_recording")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)
    try:
        x, sr = audio.read(tmp_path)
    except Exception as exc:  # noqa: BLE001
        raise ApiError("bad_recording", detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    d = st.layout.check_dir(user["id"]) / cid
    with db.tx(c):
        t = json.loads(c.execute("SELECT trials FROM checks WHERE id=?", (cid,)).fetchone()[0])
        name = f"{len(t['recordings']):02d}_{task}.wav"
        audio.write(d / name, x, sr)
        t["recordings"].append({"task": task, "file": name, "targets": [float(v) for v in (m.get("targets") or [])]})
        c.execute("UPDATE checks SET trials=? WHERE id=?", (db.dumps(t), cid))
    out = {"ok": True, "n": len(t["recordings"]), "level_db": round(audio.rms_db(x), 1)}
    # quick check of what was sung, so the browser can ask again at once and centre the next tasks on this voice
    import numpy as np

    v, _notes, _hop = checks.sung_pitch(d / name)
    voiced = v[np.isfinite(v)] if v.size else v
    out["voiced_s"] = round(float(voiced.size * _hop), 2)
    out["median_cents"] = float(np.median(voiced)) if voiced.size >= 10 else None
    return out


@router.post("/checks/{cid}/finish")
def finish(request: Request, cid: str, body: dict = Body(...)):
    c = conn(request)
    user = current_user(request)
    ch = get_or_404(c, "checks", cid)
    if ch["user_id"] != user["id"]:
        raise ApiError("not_found", 404)
    disc = [{"delta": abs(float(d["delta"])), "correct": bool(d["correct"])} for d in (body.get("discrimination") or [])]
    with db.tx(c):
        t = json.loads(c.execute("SELECT trials FROM checks WHERE id=?", (cid,)).fetchone()[0])
        t["discrimination"] = disc
        c.execute("UPDATE checks SET trials=?, status='queued' WHERE id=?", (db.dumps(t), cid))
    jid = jobs.submit(c, "score_check", {"check_id": cid}, title="시작 검사 결과 계산", owner_id=cid, user_id=user["id"])
    return {**_view(get_or_404(c, "checks", cid)), "job": jobs.get(c, jid)}


@router.get("/checks/latest")
def latest(request: Request):
    c = conn(request)
    user = current_user(request)
    r = c.execute("SELECT * FROM checks WHERE user_id=? AND status IN ('done','queued','failed') ORDER BY created_at DESC LIMIT 1", (user["id"],)).fetchone()
    if r is None:
        return {"check": None}
    out = _view(db.row(r))
    out["job"] = jobs.latest_for(c, out["id"], "score_check")
    return {"check": out}


@router.get("/checks/{cid}")
def get_check(request: Request, cid: str):
    c = conn(request)
    out = _view(get_or_404(c, "checks", cid))
    out["job"] = jobs.latest_for(c, cid, "score_check")
    return out


@router.get("/phrases/{pid}/range-check")
def range_check(request: Request, pid: str):
    """Does this phrase sit in the current user's comfortable range?  Suggests a key change if not (gyeol.coach.health)."""
    from gyeol.coach import VoiceRange, check_phrase

    c = conn(request)
    user = current_user(request)
    ph = get_or_404(c, "phrases", pid)
    if not user.get("voice_range") or not ph.get("note_cents"):
        return {"available": False, "reason": "no_range" if not user.get("voice_range") else "no_notes"}
    vr = user["voice_range"]
    notes = [n if n is not None else float("nan") for n in json.loads(ph["note_cents"])]
    pc = check_phrase(notes, VoiceRange(vr["low_cents"], vr["high_cents"], vr["tess_low_cents"], vr["tess_high_cents"], vr.get("source", "")))
    doc = {"status": pc.status, "transpose_semitones": pc.transpose_semitones, "octave_shift_cents": pc.octave_shift_cents}
    texts = [n["text"] for n in health_notices(session_s=0, day_s=0, fatigue=[], phrase_check=doc)]
    if pc.status in ("above_tessitura", "below_tessitura", "out_of_range") and not pc.transpose_semitones:
        # check_phrase found no key that fits better: the phrase is wider than the comfortable zone
        texts.append("이 소절은 음 폭이 넓어서 키를 옮기면 반대쪽 음이 불편해져요. " +
                     ("높은 음은 무리하지 말고 가볍게 내 보세요." if pc.status != "below_tessitura" else "낮은 음은 억지로 누르지 말고 가볍게 내 보세요."))
    if pc.status == "comfortable":
        texts = ["이 소절은 편한 음역 안에 있어요." + (" (한 옥타브 옮겨서 부르면 편해요)" if pc.octave_shift_cents else "")]
    return {"available": True, **doc, "texts": texts}
