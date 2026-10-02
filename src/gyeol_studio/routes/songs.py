"""Song library (upload → background separation) and phrases (range + lyrics → background target analysis)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Body, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from .. import audio, db, jobs
from ..deps import ApiError, conn, get_or_404, optional_user, state
from ..maintenance import delete_take
from ..tasks.songs import phrase_paths, queue_phrase

router = APIRouter(prefix="/api")

AUDIO_EXT = {".mp3", ".wav", ".flac", ".ogg", ".oga", ".aif", ".aiff", ".m4a", ".aac", ".opus", ".webm"}


def _song_view(c, s: dict) -> dict:
    out = dict(s)
    out["separation"] = json.loads(s["separation"]) if s.get("separation") else None
    out["n_phrases"] = c.execute("SELECT COUNT(*) FROM phrases WHERE song_id=?", (s["id"],)).fetchone()[0]
    out["job"] = jobs.latest_for(c, s["id"], "separate_song")
    return out


@router.get("/songs")
def list_songs(request: Request):
    c = conn(request)
    return {"songs": [_song_view(c, db.row(r)) for r in c.execute("SELECT * FROM songs ORDER BY created_at DESC").fetchall()]}


@router.post("/songs")
def upload_song(request: Request, file: UploadFile = File(None), title: str = Form(""), artist: str = Form(""),
                song_key: str = Form(""), vocal_only: bool = Form(False)):
    st, c = state(request), conn(request)
    user = optional_user(request)
    if file is None or not file.filename:
        raise ApiError("file_required")
    title = title.strip()[:120] or Path(file.filename).stem[:120]
    if not title:
        raise ApiError("title_required")
    ext = Path(file.filename).suffix.lower()
    if ext not in AUDIO_EXT:
        ext = ".bin"
    sid = db.new_id()
    d = st.layout.song_dir(sid)
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"original{ext}"
    with open(dest, "wb") as fh:
        shutil.copyfileobj(file.file, fh, length=1 << 20)
    try:
        x, sr = audio.read(dest)
    except Exception as exc:  # noqa: BLE001 - any decoder error means the same thing to the user
        shutil.rmtree(d, ignore_errors=True)
        raise ApiError("bad_audio", 415, detail=str(exc)) from exc
    dur = len(x) / sr
    if dur > audio.MAX_SONG_S:
        shutil.rmtree(d, ignore_errors=True)
        raise ApiError("too_long", 413)
    if dur < 1.0 or not np.any(np.abs(x) > 1e-4):
        shutil.rmtree(d, ignore_errors=True)
        raise ApiError("bad_audio", 415, message="소리가 없거나 너무 짧은 파일이에요. 다른 파일을 골라 주세요.")
    (d / "peaks.json").write_text(json.dumps(audio.peaks_payload(x, sr, max(2000, int(dur * 50)))), encoding="utf-8")  # 50 per second: sharp when zoomed in
    with db.tx(c):
        c.execute("INSERT INTO songs(id, title, artist, song_key, original_name, original_path, duration_s, sr, vocal_only, status, created_by, created_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (sid, title, artist.strip()[:120], song_key.strip()[:20], file.filename[:200], str(dest.relative_to(st.layout.root)), dur, sr,
                   int(bool(vocal_only)), "queued", user["id"] if user else None, db.now()))
    jobs.submit(c, "separate_song", {"song_id": sid}, title=f"보컬 분리: {title}", owner_id=sid, user_id=user["id"] if user else None)
    return _song_view(c, get_or_404(c, "songs", sid))


@router.get("/songs/{sid}")
def get_song(request: Request, sid: str):
    c = conn(request)
    s = _song_view(c, get_or_404(c, "songs", sid))
    s["phrases"] = [_phrase_view(c, db.row(r), brief=True) for r in c.execute("SELECT * FROM phrases WHERE song_id=? ORDER BY start_s", (sid,)).fetchall()]
    return s


@router.patch("/songs/{sid}")
def patch_song(request: Request, sid: str, body: dict = Body(...)):
    c = conn(request)
    get_or_404(c, "songs", sid)
    for k, col, n in (("title", "title", 120), ("artist", "artist", 120), ("song_key", "song_key", 20)):
        if k in body:
            v = str(body[k]).strip()[:n]
            if k == "title" and not v:
                raise ApiError("title_required")
            c.execute(f"UPDATE songs SET {col}=? WHERE id=?", (v, sid))
    return get_song(request, sid)


@router.post("/songs/{sid}/retry")
def retry_song(request: Request, sid: str):
    c = conn(request)
    s = get_or_404(c, "songs", sid)
    c.execute("UPDATE songs SET status='queued', error=NULL WHERE id=?", (sid,))
    jobs.submit(c, "separate_song", {"song_id": sid}, title=f"보컬 분리: {s['title']}", owner_id=sid)
    return get_song(request, sid)


@router.delete("/songs/{sid}")
def delete_song(request: Request, sid: str):
    st, c = state(request), conn(request)
    get_or_404(c, "songs", sid)
    for j in c.execute("SELECT id FROM jobs WHERE owner_id=? AND status IN ('queued','running')", (sid,)).fetchall():
        jobs.request_cancel(c, j[0])
    n = 0
    for p in c.execute("SELECT id FROM phrases WHERE song_id=?", (sid,)).fetchall():
        for t in c.execute("SELECT id FROM takes WHERE phrase_id=?", (p[0],)).fetchall():
            delete_take(c, st.layout, t[0])
            n += 1
        c.execute("DELETE FROM analyses WHERE owner_id=?", (p[0],))
        shutil.rmtree(st.layout.phrase_dir(p[0]), ignore_errors=True)
    c.execute("DELETE FROM songs WHERE id=?", (sid,))
    shutil.rmtree(st.layout.song_dir(sid), ignore_errors=True)
    return {"deleted": True, "takes_deleted": n}


@router.get("/songs/{sid}/peaks")
def song_peaks(request: Request, sid: str):
    st, c = state(request), conn(request)
    get_or_404(c, "songs", sid)
    return FileResponse(st.layout.song_dir(sid) / "peaks.json", media_type="application/json")


@router.get("/songs/{sid}/audio")
def song_audio(request: Request, sid: str, stem: str = "mix"):
    st, c = state(request), conn(request)
    s = get_or_404(c, "songs", sid)
    if stem == "mix":
        p = st.layout.root / s["original_path"]
    elif stem in ("vocal", "accompaniment"):
        p = st.layout.song_dir(sid) / f"{stem}.wav"
    else:
        raise ApiError("not_found", 404)
    if not p.exists():
        raise ApiError("song_not_ready", 409)
    return FileResponse(p)


# ---------------------------------------------------------------- phrases


def _target_curve(c, ph: dict, max_points: int = 500) -> dict | None:
    if not ph.get("target_analysis_id"):
        return None
    doc = json.loads(db.load_analysis_json(c, ph["target_analysis_id"]) or "{}")
    try:
        f0 = doc["curves"]["f0_cents"]
        vals, conf = f0["values"], f0["confidence"]
        hop = doc["grid"]["hop"] / doc["grid"]["sr"]
    except (KeyError, TypeError):
        return None
    n = len(vals)
    step = max(1, int(np.ceil(n / max_points)))
    cents = [None if (v is None or (cf or 0) < 0.3) else round(v, 1) for v, cf in zip(vals[::step], conf[::step])]
    syl = [{"start": s * hop, "end": e * hop, "text": t} for s, e, t in (doc.get("meta", {}).get("syllables") or [])]
    notes = doc.get("meta", {}).get("notes") or []
    return {"times": [round(i * hop, 3) for i in range(0, n, step)], "cents": cents, "syllables": syl, "n_notes": len(notes)}


def _phrase_view(c, ph: dict, brief: bool = False) -> dict:
    out = {k: ph[k] for k in ("id", "song_id", "name", "start_s", "end_s", "lyrics", "status", "error", "slice_start_s", "created_at")}
    out["note_cents"] = json.loads(ph["note_cents"]) if ph.get("note_cents") else None
    out["job"] = jobs.latest_for(c, ph["id"], "analyze_phrase")
    out["n_takes"] = c.execute("SELECT COUNT(*) FROM takes WHERE phrase_id=?", (ph["id"],)).fetchone()[0]
    if not brief:
        out["target"] = _target_curve(c, ph)
        s = db.row(c.execute("SELECT id, title, artist, song_key, status, vocal_only FROM songs WHERE id=?", (ph["song_id"],)).fetchone())
        out["song"] = s
    return out


def _check_range(start: float, end: float, duration: float) -> None:
    if not (0 <= start < end <= duration + 0.01) or not (0.5 <= end - start <= 30.0):
        raise ApiError("bad_range")


@router.post("/songs/{sid}/phrases")
def create_phrase(request: Request, sid: str, body: dict = Body(...)):
    c = conn(request)
    s = get_or_404(c, "songs", sid)
    user = optional_user(request)
    try:
        start, end = round(float(body["start_s"]), 3), round(float(body["end_s"]), 3)
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError("bad_range") from exc
    _check_range(start, end, s["duration_s"])
    n = c.execute("SELECT COUNT(*) FROM phrases WHERE song_id=?", (sid,)).fetchone()[0]
    name = str(body.get("name") or f"{n + 1}번째 소절").strip()[:60]
    lyrics = str(body.get("lyrics") or "").strip()[:300]
    pid = db.new_id()
    t = db.now()
    c.execute("INSERT INTO phrases(id, song_id, name, start_s, end_s, lyrics, status, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (pid, sid, name, start, end, lyrics, "waiting", user["id"] if user else None, t, t))
    if s["status"] == "ready":
        queue_phrase(c, pid, s["title"], name)
    return _phrase_view(c, get_or_404(c, "phrases", pid))


@router.get("/phrases/{pid}")
def get_phrase(request: Request, pid: str):
    c = conn(request)
    return _phrase_view(c, get_or_404(c, "phrases", pid))


@router.patch("/phrases/{pid}")
def patch_phrase(request: Request, pid: str, body: dict = Body(...)):
    c = conn(request)
    ph = get_or_404(c, "phrases", pid)
    s = get_or_404(c, "songs", ph["song_id"])
    reanalyze = False
    if "start_s" in body or "end_s" in body:
        start = round(float(body.get("start_s", ph["start_s"])), 3)
        end = round(float(body.get("end_s", ph["end_s"])), 3)
        if (start, end) != (ph["start_s"], ph["end_s"]):
            if c.execute("SELECT 1 FROM takes WHERE phrase_id=?", (pid,)).fetchone():
                raise ApiError("phrase_has_takes", message="이미 녹음이 있는 소절은 구간을 바꿀 수 없어요. 새 소절을 만들어 주세요.")
            _check_range(start, end, s["duration_s"])
            c.execute("UPDATE phrases SET start_s=?, end_s=? WHERE id=?", (start, end, pid))
            reanalyze = True
    if "lyrics" in body:
        lyrics = str(body["lyrics"] or "").strip()[:300]
        if lyrics != ph["lyrics"]:
            c.execute("UPDATE phrases SET lyrics=? WHERE id=?", (lyrics, pid))
            reanalyze = True
    if "name" in body:
        c.execute("UPDATE phrases SET name=? WHERE id=?", (str(body["name"]).strip()[:60] or ph["name"], pid))
    c.execute("UPDATE phrases SET updated_at=? WHERE id=?", (db.now(), pid))
    if reanalyze:
        if s["status"] == "ready":
            queue_phrase(c, pid, s["title"], ph["name"])
        else:
            c.execute("UPDATE phrases SET status='waiting' WHERE id=?", (pid,))
    return _phrase_view(c, get_or_404(c, "phrases", pid))


@router.post("/phrases/{pid}/retry")
def retry_phrase(request: Request, pid: str):
    c = conn(request)
    ph = get_or_404(c, "phrases", pid)
    s = get_or_404(c, "songs", ph["song_id"])
    if s["status"] != "ready":
        raise ApiError("song_not_ready", 409)
    queue_phrase(c, pid, s["title"], ph["name"])
    return _phrase_view(c, get_or_404(c, "phrases", pid))


@router.delete("/phrases/{pid}")
def delete_phrase(request: Request, pid: str):
    st, c = state(request), conn(request)
    get_or_404(c, "phrases", pid)
    n = 0
    for t in c.execute("SELECT id FROM takes WHERE phrase_id=?", (pid,)).fetchall():
        delete_take(c, st.layout, t[0])
        n += 1
    c.execute("DELETE FROM analyses WHERE owner_id=?", (pid,))
    c.execute("DELETE FROM phrases WHERE id=?", (pid,))
    shutil.rmtree(st.layout.phrase_dir(pid), ignore_errors=True)
    return {"deleted": True, "takes_deleted": n}


@router.get("/phrases/{pid}/audio/{stem}")
def phrase_audio(request: Request, pid: str, stem: str):
    st, c = state(request), conn(request)
    get_or_404(c, "phrases", pid)
    p = phrase_paths(st.layout, pid).get(stem)
    if p is None:
        raise ApiError("not_found", 404)
    if not p.exists():
        raise ApiError("phrase_not_ready", 409)
    return FileResponse(p, media_type="audio/wav")
