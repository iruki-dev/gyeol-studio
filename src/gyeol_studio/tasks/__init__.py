"""Job handlers, by job kind.  Each takes a :class:`~gyeol_studio.jobs.JobContext` and returns a result dict."""

from __future__ import annotations

from .. import db
from . import songs, takes

HANDLERS = {
    "fetch_weights": songs.fetch_weights,
    "separate_song": songs.separate_song,
    "analyze_phrase": songs.analyze_phrase,
    "analyze_take": takes.analyze_take,
    "render_demo": takes.render_demo,
}

# where a job's failure shows up besides the job list
_OWNER_TABLE = {"separate_song": "songs", "analyze_phrase": "phrases", "analyze_take": "takes"}


def register(kind: str, fn, owner_table: str | None = None) -> None:
    HANDLERS[kind] = fn
    if owner_table:
        _OWNER_TABLE[kind] = owner_table


def on_failed(conn, job: dict, message: str, layout) -> None:
    if job["kind"] == "render_demo" and job.get("owner_id"):  # owner is "<take id>:<item key>"
        tid, key = job["owner_id"].split(":", 1)
        conn.execute("UPDATE demos SET status='failed', error=? WHERE take_id=? AND item_key=?", (message, tid, key))
    table = _OWNER_TABLE.get(job["kind"])
    if table and job.get("owner_id"):
        conn.execute(f"UPDATE {table} SET status='failed', error=? WHERE id=?", (message, job["owner_id"]))
    if job["kind"] == "train" and job.get("owner_id"):
        conn.execute("UPDATE training_runs SET status='failed' WHERE id=?", (job["owner_id"],))


def on_cancelled(conn, job: dict, layout) -> None:
    if job["kind"] == "render_demo" and job.get("owner_id"):
        tid, key = job["owner_id"].split(":", 1)
        conn.execute("DELETE FROM demos WHERE take_id=? AND item_key=?", (tid, key))
    table = _OWNER_TABLE.get(job["kind"])
    if table and job.get("owner_id"):
        conn.execute(f"UPDATE {table} SET status='cancelled', error=NULL WHERE id=?", (job["owner_id"],))


def _register_later_phases() -> None:
    """Handlers of later phases live in their own modules; importing them registers them."""
    import importlib

    for mod in ("checks", "export", "training"):
        try:
            importlib.import_module(f"{__name__}.{mod}")
        except ModuleNotFoundError as exc:
            if exc.name != f"{__name__}.{mod}":
                raise


_register_later_phases()
__all__ = ["HANDLERS", "db", "on_cancelled", "on_failed", "register"]
