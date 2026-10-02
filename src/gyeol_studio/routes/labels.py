"""Labels on takes (a few taps per recording) and the labelling queue."""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Request

from .. import db, labels
from ..deps import ApiError, conn, current_user, get_or_404

router = APIRouter(prefix="/api")


@router.get("/labels/vocab")
def vocab():
    return labels.vocab()


def _label(c, tid: str) -> dict | None:
    r = db.row(c.execute("SELECT * FROM labels WHERE take_id=?", (tid,)).fetchone())
    if r is None:
        return None
    return {"register": r["register"], "qualities": json.loads(r["qualities"]) if r["qualities"] else None, "rhythm": r["rhythm"],
            "memo": r["memo"], "labeled_by": r["labeled_by"], "updated_at": r["updated_at"]}


@router.get("/takes/{tid}/labels")
def get_labels(request: Request, tid: str):
    c = conn(request)
    get_or_404(c, "takes", tid)
    return {"labels": _label(c, tid)}


@router.put("/takes/{tid}/labels")
def put_labels(request: Request, tid: str, body: dict = Body(...)):
    c = conn(request)
    get_or_404(c, "takes", tid)
    user = current_user(request)
    v = labels.clean(body)
    c.execute("INSERT INTO labels(take_id, register, qualities, rhythm, memo, labeled_by, updated_at) VALUES(?,?,?,?,?,?,?) "
              "ON CONFLICT(take_id) DO UPDATE SET register=excluded.register, qualities=excluded.qualities, rhythm=excluded.rhythm, "
              "memo=excluded.memo, labeled_by=excluded.labeled_by, updated_at=excluded.updated_at",
              (tid, v["register"], db.dumps(v["qualities"]) if v["qualities"] is not None else None, v["rhythm"], v["memo"], user["id"], db.now()))
    return {"labels": _label(c, tid)}


@router.get("/data/takes")
def label_queue(request: Request, who: str = "mine", unlabeled: bool = False, limit: int = 60, offset: int = 0):
    """Takes to label, newest first, with song/phrase context."""
    c = conn(request)
    user = current_user(request)
    q = ("SELECT t.*, u.name AS user_name, p.lyrics, p.name AS phrase_name, s.title AS song_title FROM takes t "
         "JOIN users u ON u.id=t.user_id JOIN phrases p ON p.id=t.phrase_id JOIN songs s ON s.id=p.song_id")
    where, args = [], []
    if who == "mine":
        where.append("t.user_id=?")
        args.append(user["id"])
    if unlabeled:
        where.append("NOT EXISTS (SELECT 1 FROM labels l WHERE l.take_id=t.id)")
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY t.created_at DESC LIMIT ? OFFSET ?"
    rs = c.execute(q, (*args, max(1, min(limit, 200)), max(0, offset))).fetchall()
    out = []
    for r in rs:
        d = dict(r)
        out.append({"id": d["id"], "user_id": d["user_id"], "user_name": d["user_name"], "song_title": d["song_title"], "phrase_name": d["phrase_name"],
                    "lyrics": d["lyrics"], "created_at": d["created_at"], "kind": d["kind"], "status": d["status"], "technique": json.loads(d["technique"]) if d["technique"] else None,
                    "pair_role": d["pair_role"], "conditions": json.loads(d["conditions"]) if d["conditions"] else {}, "labels": _label(c, d["id"]),
                    "consent_training": bool(d["consent_training"]), "consent_commercial": bool(d["consent_commercial"])})
    return {"takes": out}


@router.get("/data/summary")
def summary(request: Request):
    c = conn(request)
    one = lambda q, *a: c.execute(q, a).fetchone()[0]  # noqa: E731
    resp = c.execute("SELECT r.item_key, r.response, COUNT(*) n FROM feedback_responses r "
                     "GROUP BY 1, 2").fetchall()
    by: dict = {}
    for r in resp:
        cat, attr, _ = r["item_key"].split(":")
        k = f"{cat}:{attr}"
        by.setdefault(k, {"agree": 0, "disagree": 0, "unsure": 0})[r["response"]] += r["n"]
    return {
        "takes": one("SELECT COUNT(*) FROM takes"),
        "people": one("SELECT COUNT(DISTINCT user_id) FROM takes"),
        "labeled": one("SELECT COUNT(*) FROM labels"),
        "training_ok": one("SELECT COUNT(*) FROM takes WHERE consent_training=1"),
        "commercial_ok": one("SELECT COUNT(*) FROM takes WHERE consent_commercial=1"),
        "technique_takes": one("SELECT COUNT(*) FROM takes WHERE kind='technique'"),
        "responses": one("SELECT COUNT(*) FROM feedback_responses"),
        "responses_by_item": by,
    }


@router.get("/data/takes/{tid}")
def take_detail(request: Request, tid: str):
    c = conn(request)
    t = get_or_404(c, "takes", tid)
    if t["user_id"] is None:
        raise ApiError("not_found", 404)
    return {"labels": _label(c, tid)}
