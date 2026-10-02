"""Takes (sing-along recordings), their feedback, responses and demos."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from .. import audio, coaching, consent, db, jobs
from ..deps import ApiError, conn, current_user, get_or_404, state
from ..maintenance import delete_take

router = APIRouter(prefix="/api")

CONDITION_KEYS = {"device": 40, "earphone": 20, "backing": 10, "place": 40, "mic": 40}
RESPONSES = ("agree", "disagree", "unsure")


def _session_key(c, user_id: str, gap_min: float) -> str:
    r = c.execute("SELECT session_key, created_at FROM takes WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (user_id,)).fetchone()
    if r and db.now() - r["created_at"] <= gap_min * 60:
        return r["session_key"]
    return db.new_id()


def _clean_conditions(raw) -> dict:
    out = {}
    for k, n in CONDITION_KEYS.items():
        v = (raw or {}).get(k)
        if v not in (None, ""):
            out[k] = str(v)[:n]
    return out


def _take_view(c, t: dict, brief: bool = True) -> dict:
    out = {k: t[k] for k in ("id", "phrase_id", "user_id", "kind", "sr", "duration_s", "created_at", "session_key", "latency_ms",
                             "latency_method", "status", "error", "voiced_s", "pair_id", "pair_role", "technique",
                             "consent_training", "consent_commercial", "retain_until")}
    out["conditions"] = json.loads(t["conditions"]) if isinstance(t.get("conditions"), str) else t.get("conditions")
    out["job"] = jobs.latest_for(c, t["id"], "analyze_take") if t["status"] not in ("ready",) else None
    fb = c.execute("SELECT coaching, noticed FROM feedback WHERE take_id=?", (t["id"],)).fetchone()
    if fb:
        doc = json.loads(fb["coaching"])
        revealed = fb["noticed"] is not None
        out["feedback"] = {"revealed": revealed,
                           "primary": (doc["primary"] or {}).get("text") if revealed and doc.get("primary") else None,
                           "primary_category": (doc["primary"] or {}).get("category_label") if revealed and doc.get("primary") else None}
    lab = c.execute("SELECT * FROM labels WHERE take_id=?", (t["id"],)).fetchone()
    out["labels"] = _label_view(db.row(lab)) if lab else None
    return out


def _label_view(lab: dict) -> dict:
    return {"register": lab["register"], "qualities": json.loads(lab["qualities"]) if lab["qualities"] else None,
            "rhythm": lab["rhythm"], "memo": lab["memo"], "labeled_by": lab["labeled_by"], "updated_at": lab["updated_at"]}


@router.post("/phrases/{pid}/takes")
def upload_take(request: Request, pid: str, file: UploadFile = File(...), meta: str = Form("{}")):
    st, c = state(request), conn(request)
    user = current_user(request)
    if not user["consent_analysis"]:
        raise ApiError("consent_required", 403)
    ph = get_or_404(c, "phrases", pid)
    if ph["status"] != "ready":
        raise ApiError("phrase_not_ready", 409)
    try:
        m = json.loads(meta or "{}")
        offset = float(m.get("phrase_offset_s", 0.0))
    except (ValueError, TypeError) as exc:
        raise ApiError("bad_recording") from exc
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)
    try:
        raw, sr = audio.read(tmp_path)
    except Exception as exc:  # noqa: BLE001
        raise ApiError("bad_recording", detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    dur = ph["end_s"] - ph["start_s"]
    take, covered = audio.trim_take(raw, sr, offset, dur)
    if covered < 0.7:
        raise ApiError("recording_too_short")
    if audio.rms_db(take) < -70:
        raise ApiError("bad_recording", message="소리가 거의 녹음되지 않았어요. 마이크가 연결되어 있는지, 브라우저에 마이크 권한을 줬는지 확인해 주세요.")
    tid = db.new_id()
    path = st.layout.take_path(user["id"], tid)
    audio.write(path, take, sr)
    snap = consent.take_snapshot(user)
    kind = "technique" if m.get("kind") == "technique" else "practice"
    with db.tx(c):
        c.execute("INSERT INTO takes(id, phrase_id, user_id, kind, audio_path, sr, duration_s, created_at, session_key, latency_ms, latency_method, "
                  "conditions, consent_analysis, consent_training, consent_commercial, consent_at, retain_until, status, pair_id, pair_role, technique) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (tid, pid, user["id"], kind, str(path.relative_to(st.layout.root)), sr, len(take) / sr, db.now(),
                   _session_key(c, user["id"], st.settings.advanced.session_gap_min),
                   float(m["latency_ms"]) if m.get("latency_ms") is not None else None, str(m.get("latency_method") or "")[:20] or None,
                   db.dumps(_clean_conditions(m.get("conditions"))), snap["consent_analysis"], snap["consent_training"], snap["consent_commercial"],
                   snap["consent_at"], snap["retain_until"], "queued",
                   str(m["pair_id"])[:40] if m.get("pair_id") else None, str(m["pair_role"])[:20] if m.get("pair_role") else None,
                   db.dumps(m["technique"]) if m.get("technique") else None))
    jobs.submit(c, "analyze_take", {"take_id": tid}, title="녹음 분석", owner_id=tid, user_id=user["id"])
    return _take_view(c, get_or_404(c, "takes", tid))


@router.get("/phrases/{pid}/takes")
def list_takes(request: Request, pid: str, all_users: bool = False):
    c = conn(request)
    get_or_404(c, "phrases", pid)
    if all_users:
        rs = c.execute("SELECT * FROM takes WHERE phrase_id=? ORDER BY created_at DESC", (pid,)).fetchall()
    else:
        user = current_user(request)
        rs = c.execute("SELECT * FROM takes WHERE phrase_id=? AND user_id=? ORDER BY created_at DESC", (pid, user["id"])).fetchall()
    return {"takes": [_take_view(c, db.row(r)) for r in rs]}


@router.get("/takes/{tid}")
def get_take(request: Request, tid: str):
    c = conn(request)
    return _take_view(c, get_or_404(c, "takes", tid))


@router.get("/takes/{tid}/audio")
def take_audio(request: Request, tid: str):
    st, c = state(request), conn(request)
    t = get_or_404(c, "takes", tid)
    return FileResponse(st.layout.root / t["audio_path"], media_type="audio/wav")


@router.get("/takes/{tid}/peaks")
def take_peaks(request: Request, tid: str, n: int = 400):
    st, c = state(request), conn(request)
    t = get_or_404(c, "takes", tid)
    x, sr = audio.read(st.layout.root / t["audio_path"])
    return audio.peaks_payload(x, sr, max(50, min(n, 2000)))


@router.delete("/takes/{tid}")
def remove_take(request: Request, tid: str):
    st, c = state(request), conn(request)
    get_or_404(c, "takes", tid)
    for j in c.execute("SELECT id FROM jobs WHERE owner_id=? AND status IN ('queued','running')", (tid,)).fetchall():
        jobs.request_cancel(c, j[0])
    delete_take(c, st.layout, tid)
    return {"deleted": True}


@router.post("/takes/{tid}/retry")
def retry_take(request: Request, tid: str):
    c = conn(request)
    t = get_or_404(c, "takes", tid)
    c.execute("UPDATE takes SET status='queued', error=NULL WHERE id=?", (tid,))
    jobs.submit(c, "analyze_take", {"take_id": tid}, title="녹음 분석", owner_id=tid, user_id=t["user_id"])
    return _take_view(c, get_or_404(c, "takes", tid))


# ---------------------------------------------------------------- feedback


def _feedback_payload(c, t: dict) -> dict:
    fb = db.row(c.execute("SELECT * FROM feedback WHERE take_id=?", (t["id"],)).fetchone(), ("coaching", "evidence", "noticed"))
    q = coaching.strings()["self_assessment"]["question"]
    base = {"take_id": t["id"], "status": t["status"], "error": t["error"], "question": q,
            "options": [{"id": k, "label": v} for k, v in coaching.SELF_ASSESSMENT]}
    if fb is None:
        base["job"] = jobs.latest_for(c, t["id"], "analyze_take")
        base["revealed"] = False
        return base
    base["feedback_id"] = fb["id"]
    base["revealed"] = fb["noticed"] is not None
    if not base["revealed"]:
        return base
    doc = fb["coaching"]
    base["self_assessment"] = coaching.self_assessment_result(fb["noticed"], doc)
    base["coaching"] = doc
    base["evidence"] = fb["evidence"]
    base["responses"] = {r["item_key"]: r["response"] for r in c.execute("SELECT item_key, response FROM feedback_responses WHERE feedback_id=?",
                                                                       (fb["id"],)).fetchall()}
    base["demos"] = _demos(c, t["id"])
    base["strings"] = {k: coaching.strings()["feedback"][k] for k in ("tentative", "experimental", "thresholds_synthetic", "primary", "secondary")}
    return base


def _demos(c, tid: str) -> dict:
    out = {}
    for d in db.rows(c.execute("SELECT * FROM demos WHERE take_id=?", (tid,)).fetchall(), ("files", "meta")):
        steps = []
        if d["meta"]:
            steps = [{"label": s.get("label"), "applied": s.get("applied")} for s in d["meta"].get("steps", [])]
        out[d["item_key"]] = {"status": d["status"], "error": d["error"], "files": d["files"], "steps": steps,
                              "job": jobs.latest_for(c, f"{tid}:{d['item_key']}", "render_demo") if d["status"] != "ready" else None}
    return out


@router.get("/takes/{tid}/feedback")
def get_feedback(request: Request, tid: str):
    c = conn(request)
    return _feedback_payload(c, get_or_404(c, "takes", tid))


@router.post("/takes/{tid}/self-assessment")
def self_assessment(request: Request, tid: str, body: dict = Body(...)):
    c = conn(request)
    t = get_or_404(c, "takes", tid)
    noticed = [str(x) for x in (body.get("noticed") or [])]
    valid = {k for k, _ in coaching.SELF_ASSESSMENT}
    if not noticed or any(n not in valid for n in noticed):
        raise ApiError("bad_response", message="느낀 점을 하나 이상 골라 주세요. 잘 모르겠으면 '잘 모르겠어요'를 골라 주세요.")
    fb = c.execute("SELECT id FROM feedback WHERE take_id=?", (tid,)).fetchone()
    if fb is None:
        raise ApiError("feedback_not_ready", 409)
    c.execute("UPDATE feedback SET noticed=?, noticed_at=? WHERE id=?", (db.dumps(noticed), db.now(), fb["id"]))
    return _feedback_payload(c, t)


@router.post("/feedback/{fid}/responses")
def respond(request: Request, fid: str, body: dict = Body(...)):
    c = conn(request)
    fb = get_or_404(c, "feedback", fid, ("coaching",))
    user = current_user(request)
    key, resp = str(body.get("item_key", "")), str(body.get("response", ""))
    doc = fb["coaching"]
    shown = {i["key"] for i in [doc.get("primary") or {}] + (doc.get("secondary") or []) if i}
    if key not in shown or resp not in RESPONSES:
        raise ApiError("bad_response")
    c.execute("INSERT INTO feedback_responses(feedback_id, take_id, user_id, item_key, response, created_at) VALUES(?,?,?,?,?,?) "
              "ON CONFLICT(feedback_id, item_key) DO UPDATE SET response=excluded.response, created_at=excluded.created_at, user_id=excluded.user_id",
              (fid, fb["take_id"], user["id"], key, resp, db.now()))
    return {"item_key": key, "response": resp}


@router.post("/takes/{tid}/demo")
def request_demo(request: Request, tid: str, body: dict = Body(...)):
    c = conn(request)
    t = get_or_404(c, "takes", tid)
    key = str(body.get("item_key", ""))
    fb = db.row(c.execute("SELECT coaching FROM feedback WHERE take_id=?", (tid,)).fetchone(), ("coaching",))
    if fb is None:
        raise ApiError("feedback_not_ready", 409)
    doc = fb["coaching"]
    if key not in {i["key"] for i in [doc.get("primary") or {}] + (doc.get("secondary") or []) if i}:
        raise ApiError("bad_response")
    d = c.execute("SELECT status FROM demos WHERE take_id=? AND item_key=?", (tid, key)).fetchone()
    if d and d["status"] in ("ready", "rendering"):
        return {"demos": _demos(c, tid)}
    c.execute("INSERT INTO demos(id, take_id, item_key, status, created_at) VALUES(?,?,?,?,?) "
              "ON CONFLICT(take_id, item_key) DO UPDATE SET status='queued', error=NULL", (db.new_id(), tid, key, "queued", db.now()))
    jobs.submit(c, "render_demo", {"take_id": tid, "item_key": key}, title="시범음 만들기", owner_id=f"{tid}:{key}", user_id=t["user_id"])
    return {"demos": _demos(c, tid)}


@router.get("/files/{path:path}")
def data_file(request: Request, path: str):
    """Generated audio under the data folder (demos only)."""
    st = state(request)
    p = (st.layout.root / path).resolve()
    root = (st.layout.root / "demos").resolve()
    if root not in p.parents or not p.is_file():
        raise ApiError("not_found", 404)
    return FileResponse(p, media_type="audio/wav")

