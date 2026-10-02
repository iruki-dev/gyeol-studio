"""Deleting people's data: per-user deletion, single takes, and the retention sweep."""

from __future__ import annotations

import logging
import shutil
import threading

from . import db

log = logging.getLogger("gyeol_studio")


def _delete_take_files(layout, take: dict) -> int:
    n = 0
    p = layout.root / take["audio_path"]
    if p.exists():
        p.unlink()
        n += 1
    d = layout.root / "demos" / take["id"]
    if d.exists():
        n += sum(1 for f in d.rglob("*") if f.is_file())
        shutil.rmtree(d, ignore_errors=True)
    return n


def delete_take(conn, layout, take_id: str) -> int:
    take = db.row(conn.execute("SELECT * FROM takes WHERE id=?", (take_id,)).fetchone())
    if take is None:
        return 0
    n = _delete_take_files(layout, take)
    with db.tx(conn):
        conn.execute("DELETE FROM analyses WHERE owner_id=?", (take_id,))
        conn.execute("DELETE FROM takes WHERE id=?", (take_id,))  # feedback, responses, labels, demos cascade
    return n


def delete_user(conn, layout, user_id: str) -> dict:
    """Remove every recording, analysis, label, response, check and consent record of a user.

    A deletion-log line (random user id, time and counts — no name, no voice data) is kept so the deletion itself
    can be shown later.
    """
    takes = db.rows(conn.execute("SELECT * FROM takes WHERE user_id=?", (user_id,)).fetchall())
    files = sum(_delete_take_files(layout, t) for t in takes)
    cdir = layout.check_dir(user_id)
    if cdir.exists():
        files += sum(1 for f in cdir.rglob("*") if f.is_file())
        shutil.rmtree(cdir, ignore_errors=True)
    tdir = layout.root / "takes" / user_id
    if tdir.exists():
        shutil.rmtree(tdir, ignore_errors=True)
    from .exporting import remove_exports_with_user

    counts = {"takes": len(takes), "files": files, "export_folders": remove_exports_with_user(layout, user_id),
              "training_runs": _remove_from_training(conn, layout, user_id)}
    with db.tx(conn):
        for t in takes:
            conn.execute("DELETE FROM analyses WHERE owner_id=?", (t["id"],))
        for ch in conn.execute("SELECT id FROM checks WHERE user_id=?", (user_id,)).fetchall():
            conn.execute("DELETE FROM analyses WHERE owner_id=?", (ch[0],))
        counts["labels_given"] = conn.execute("UPDATE labels SET labeled_by=NULL WHERE labeled_by=?", (user_id,)).rowcount
        conn.execute("DELETE FROM takes WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM checks WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM feedback_responses WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM consents WHERE user_id=?", (user_id,))
        conn.execute("UPDATE songs SET created_by=NULL WHERE created_by=?", (user_id,))
        conn.execute("UPDATE phrases SET created_by=NULL WHERE created_by=?", (user_id,))
        conn.execute("UPDATE jobs SET user_id=NULL WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.execute("INSERT INTO deletion_log(user_id, deleted_at, counts) VALUES(?,?,?)", (user_id, db.now(), db.dumps(counts)))
    return counts


def _remove_from_training(conn, layout, user_id: str) -> int:
    """Training runs that used this person's recordings lose their copied audio and prepared features.

    The trained weights stay (a network cannot "unlearn" one person); the run is marked so the screen can say so.
    """
    import json

    n = 0
    for r in conn.execute("SELECT id, data_summary FROM training_runs WHERE data_summary IS NOT NULL").fetchall():
        users = (json.loads(r["data_summary"]) or {}).get("users", [])
        if user_id in users:
            d = layout.training / "runs" / r["id"]
            shutil.rmtree(d / "data", ignore_errors=True)
            shutil.rmtree(d / "cache", ignore_errors=True)
            n += 1
    return n


def sweep_retention(conn, layout, now: float | None = None) -> int:
    """Delete takes whose retention period has ended."""
    t = db.now() if now is None else now
    ids = [r[0] for r in conn.execute("SELECT id FROM takes WHERE retain_until IS NOT NULL AND retain_until < ?", (t,)).fetchall()]
    for i in ids:
        delete_take(conn, layout, i)
    if ids:
        log.info("retention: deleted %d takes", len(ids))
    return len(ids)


def startup_maintenance(state, every_s: float = 6 * 3600) -> None:
    """Run the retention sweep now and every few hours while the app is open."""
    stop = threading.Event()
    while True:
        try:
            c = db.connect(state.layout.db)
            sweep_retention(c, state.layout)
            c.close()
        except Exception:  # noqa: BLE001 - maintenance must never take the app down
            log.exception("retention sweep failed")
        if stop.wait(every_s):
            return
