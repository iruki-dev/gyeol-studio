"""People (simple profiles chosen by name) and their consent."""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Request

from .. import consent, db
from ..deps import ApiError, conn, get_or_404, state, user_id_of
from ..maintenance import delete_user

router = APIRouter(prefix="/api")


def _view(u: dict, c=None) -> dict:
    out = {k: u[k] for k in ("id", "name", "created_at", "level", "consent_analysis", "consent_training", "consent_commercial",
                             "consent_at", "consent_version", "retention_days")}
    for k in ("consent_analysis", "consent_training", "consent_commercial"):
        out[k] = bool(out[k])
    vr = u.get("voice_range")
    out["voice_range"] = json.loads(vr) if isinstance(vr, str) else vr
    ob = u.get("onboarding")
    out["onboarding"] = json.loads(ob) if isinstance(ob, str) else ob
    if c is not None:
        out["n_takes"] = c.execute("SELECT COUNT(*) FROM takes WHERE user_id=?", (u["id"],)).fetchone()[0]
    return out


@router.get("/consent")
def consent_text(request: Request):
    return consent.load_text(state(request).layout)


@router.get("/users")
def list_users(request: Request):
    c = conn(request)
    return {"users": [_view(db.row(r), c) for r in c.execute("SELECT * FROM users ORDER BY name").fetchall()]}


@router.post("/users")
def create_user(request: Request, body: dict = Body(...)):
    c = conn(request)
    name = str(body.get("name", "")).strip()[:40]
    if not name:
        raise ApiError("name_required")
    text = consent.load_text(state(request).layout)
    choice = consent.normalise(body.get("consent") or {}, text)
    if not choice["analysis"]:
        raise ApiError("consent_required")
    if c.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone():
        raise ApiError("user_exists", 409)
    uid = db.new_id()
    level = body.get("level") if body.get("level") in ("beginner", "intermediate", "advanced") else "beginner"
    with db.tx(c):
        c.execute("INSERT INTO users(id, name, created_at, level) VALUES(?,?,?,?)", (uid, name, db.now(), level))
        consent.record(c, uid, choice, str(text.get("version", "")))
    return _view(get_or_404(c, "users", uid), c)


@router.get("/users/{uid}")
def get_user(request: Request, uid: str):
    c = conn(request)
    return _view(get_or_404(c, "users", uid), c)


@router.patch("/users/{uid}")
def patch_user(request: Request, uid: str, body: dict = Body(...)):
    c = conn(request)
    get_or_404(c, "users", uid)
    with db.tx(c):
        if "name" in body:
            name = str(body["name"]).strip()[:40]
            if not name:
                raise ApiError("name_required")
            if c.execute("SELECT 1 FROM users WHERE name=? AND id<>?", (name, uid)).fetchone():
                raise ApiError("user_exists", 409)
            c.execute("UPDATE users SET name=? WHERE id=?", (name, uid))
        if body.get("level") in ("beginner", "intermediate", "advanced"):
            c.execute("UPDATE users SET level=? WHERE id=?", (body["level"], uid))
        if "consent" in body:
            text = consent.load_text(state(request).layout)
            choice = consent.normalise(body["consent"], text)
            if not choice["analysis"]:
                raise ApiError("consent_required")
            consent.record(c, uid, choice, str(text.get("version", "")))
    return _view(get_or_404(c, "users", uid), c)


@router.get("/users/{uid}/consents")
def consent_history(request: Request, uid: str):
    c = conn(request)
    get_or_404(c, "users", uid)
    return {"history": db.rows(c.execute("SELECT * FROM consents WHERE user_id=? ORDER BY at", (uid,)).fetchall())}


@router.delete("/users/{uid}")
def remove_user(request: Request, uid: str, body: dict = Body(default={})):
    c = conn(request)
    u = get_or_404(c, "users", uid)
    if str((body or {}).get("confirm_name", "")).strip() != u["name"]:
        raise ApiError("confirm_mismatch", message="확인을 위해 지울 사용자의 이름을 정확히 입력해 주세요.")
    counts = delete_user(c, state(request).layout, uid)
    return {"deleted": True, "counts": counts, "was_current": user_id_of(request) == uid}
