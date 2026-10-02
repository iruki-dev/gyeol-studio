"""Consent: the wording (an editable config file) and per-user records.

The wording lives in ``<data>/config/consent.ko.json`` — copied from the app's
default on first use, so a team member can edit it without touching code.  Each
grant is kept in ``consents`` (history) and the current state on ``users``;
every take copies the owner's consent scope, date and retention when it is
recorded.  The approach follows gyeol's ``reference_service`` store
(per-purpose flags with history, retention, user deletion with a
non-biometric deletion log), kept in SQLite here.
"""

from __future__ import annotations

import json
import shutil
from importlib import resources
from pathlib import Path

from . import db

PURPOSES = ("analysis", "training", "commercial")


def text_path(layout) -> Path:
    return layout.config / "consent.ko.json"


def load_text(layout) -> dict:
    p = text_path(layout)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        with resources.as_file(resources.files("gyeol_studio").joinpath("resources/consent.ko.json")) as src:
            shutil.copyfile(src, p)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:  # a broken edit must not lock people out: fall back to the shipped wording
        return json.loads(resources.files("gyeol_studio").joinpath("resources/consent.ko.json").read_text(encoding="utf-8"))


def normalise(choice: dict, text: dict) -> dict:
    out = {p: bool(choice.get(p)) for p in PURPOSES}
    if not out["training"]:
        out["commercial"] = False
    days = int(choice.get("retention_days", text.get("retention", {}).get("default", 365)))
    allowed = {o["days"] for o in text.get("retention", {}).get("options", [])} or {days}
    out["retention_days"] = days if days in allowed else text.get("retention", {}).get("default", 365)
    return out


def record(conn, user_id: str, choice: dict, version: str) -> None:
    t = db.now()
    conn.execute("INSERT INTO consents(user_id, analysis, training, commercial, retention_days, text_version, at) VALUES(?,?,?,?,?,?,?)",
                 (user_id, int(choice["analysis"]), int(choice["training"]), int(choice["commercial"]), choice["retention_days"], version, t))
    conn.execute("UPDATE users SET consent_analysis=?, consent_training=?, consent_commercial=?, consent_at=?, consent_version=?, retention_days=? "
                 "WHERE id=?", (int(choice["analysis"]), int(choice["training"]), int(choice["commercial"]), t, version, choice["retention_days"], user_id))
    # withdrawn purposes also apply to recordings made earlier (they are not used for that purpose any more)
    for p in ("training", "commercial"):
        if not choice[p]:
            conn.execute(f"UPDATE takes SET consent_{p}=0 WHERE user_id=?", (user_id,))


def take_snapshot(user: dict) -> dict:
    """Consent scope, date and retention copied onto a new take."""
    days = int(user.get("retention_days") or 0)
    t = db.now()
    return {"consent_analysis": int(user["consent_analysis"]), "consent_training": int(user["consent_training"]),
            "consent_commercial": int(user["consent_commercial"]), "consent_at": user.get("consent_at"),
            "retain_until": (t + days * 86400.0) if days > 0 else None}
