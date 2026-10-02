"""Background jobs, stored in SQLite so they survive closing the app.

Three worker processes take jobs from their own pool:

* ``fast``  — analysing a phrase or a take, coaching, demos, start-check scoring, exports;
* ``slow``  — downloading model weights and separating songs (minutes);
* ``train`` — data preparation and training (hours; can be paused and resumed).

Jobs that were running when the app closed are queued again on the next start
(``recover``); a paused training run waits for the user to resume it.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from . import db

POOL_OF = {
    "fetch_weights": "slow",
    "separate_song": "slow",
    "analyze_phrase": "fast",
    "analyze_take": "fast",
    "render_demo": "fast",
    "score_check": "fast",
    "export_data": "fast",
    "train": "train",
}
POOLS = ("fast", "slow", "train")
ACTIVE = ("queued", "running")
# jobs whose handler cannot stop part-way: cancelling them restarts their worker process
NON_COOPERATIVE = {"separate_song", "fetch_weights"}
JOB_COLUMNS = ("id", "kind", "pool", "title", "owner_id", "user_id", "status", "progress", "eta_s", "message", "result", "error",
               "error_detail", "cancel_requested", "created_at", "started_at", "updated_at", "finished_at")


class JobCancelled(Exception):
    pass


class UserError(Exception):
    """A failure the user can act on: ``message`` is shown as is (Korean); ``detail`` goes under "자세히"."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message, self.detail = message, detail


def submit(conn: sqlite3.Connection, kind: str, params: dict, *, title: str, owner_id: str | None = None, user_id: str | None = None,
           dedupe: bool = True) -> int:
    """Queue a job (or return the id of the same kind of job for the same owner that is already queued or running)."""
    with db.tx(conn):
        if dedupe and owner_id is not None:
            r = conn.execute("SELECT id FROM jobs WHERE kind=? AND owner_id=? AND status IN ('queued','running') ORDER BY id DESC LIMIT 1",
                             (kind, owner_id)).fetchone()
            if r:
                return int(r[0])
        t = db.now()
        cur = conn.execute(
            "INSERT INTO jobs(kind, pool, params, title, owner_id, user_id, status, message, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (kind, POOL_OF[kind], db.dumps(params), title, owner_id, user_id, "queued", "차례를 기다리는 중", t, t))
        return int(cur.lastrowid)


def claim(conn: sqlite3.Connection, pool: str, pid: int) -> dict | None:
    with db.tx(conn):
        r = conn.execute("SELECT * FROM jobs WHERE status='queued' AND pool=? ORDER BY id LIMIT 1", (pool,)).fetchone()
        if r is None:
            return None
        t = db.now()
        conn.execute("UPDATE jobs SET status='running', started_at=COALESCE(started_at, ?), updated_at=?, worker_pid=?, message=? WHERE id=?",
                     (t, t, pid, "시작하는 중", r["id"]))
    job = db.row(r, ("params",))
    job["status"] = "running"
    return job


def get(conn: sqlite3.Connection, job_id: int) -> dict | None:
    return public(db.row(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()))


def public(j: dict | None) -> dict | None:
    if j is None:
        return None
    out = {k: j.get(k) for k in JOB_COLUMNS}
    if isinstance(out.get("result"), str):
        out["result"] = json.loads(out["result"])
    return out


def update(conn: sqlite3.Connection, job_id: int, **fields: Any) -> None:
    fields["updated_at"] = db.now()
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*[db.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()], job_id))


def finish(conn: sqlite3.Connection, job_id: int, result: dict | None = None, message: str = "끝났어요") -> None:
    update(conn, job_id, status="done", progress=1.0, eta_s=0.0, message=message, result=result or {}, finished_at=db.now())


def fail(conn: sqlite3.Connection, job_id: int, message: str, detail: str = "") -> None:
    update(conn, job_id, status="failed", message=message, error=message, error_detail=detail, finished_at=db.now(), eta_s=None)


def mark(conn: sqlite3.Connection, job_id: int, status: str, message: str) -> None:
    update(conn, job_id, status=status, message=message, finished_at=db.now() if status in ("cancelled",) else None, eta_s=None)


def request_cancel(conn: sqlite3.Connection, job_id: int) -> dict | None:
    """Queued jobs are cancelled at once; running ones are asked to stop."""
    with db.tx(conn):
        j = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if j is None:
            return None
        if j["status"] == "queued":
            update(conn, job_id, status="cancelled", message="취소했어요", finished_at=db.now())
        elif j["status"] == "running":
            update(conn, job_id, cancel_requested=1, message="멈추는 중…")
    return get(conn, job_id)


def requeue(conn: sqlite3.Connection, job_id: int, params: dict | None = None) -> None:
    fields: dict[str, Any] = dict(status="queued", cancel_requested=0, message="차례를 기다리는 중", error=None, error_detail=None,
                                  finished_at=None, eta_s=None, worker_pid=None)
    if params is not None:
        fields["params"] = params
    update(conn, job_id, **fields)


def recover(conn: sqlite3.Connection) -> int:
    """At start-up: jobs left running by a closed app go back to the queue (they resume from their saved state)."""
    with db.tx(conn):
        n = conn.execute("UPDATE jobs SET status='queued', worker_pid=NULL, cancel_requested=0, message='앱을 다시 열어서 이어서 하는 중', "
                         "updated_at=? WHERE status='running'", (db.now(),)).rowcount
    return n


def active(conn: sqlite3.Connection, user_id: str | None = None, recent_s: float = 20.0) -> list[dict]:
    """Queued/running/paused jobs, plus jobs that ended in the last ``recent_s`` seconds (so the UI can show the result)."""
    t = db.now() - recent_s
    rs = conn.execute("SELECT * FROM jobs WHERE status IN ('queued','running','paused') OR (finished_at IS NOT NULL AND finished_at > ?) "
                      "ORDER BY id", (t,)).fetchall()
    out = [public(db.row(r)) for r in rs]
    if user_id is not None:
        out = [j for j in out if j["user_id"] in (None, user_id)]
    return out


def latest_for(conn: sqlite3.Connection, owner_id: str, kind: str | None = None) -> dict | None:
    q = "SELECT * FROM jobs WHERE owner_id=?" + (" AND kind=?" if kind else "") + " ORDER BY id DESC LIMIT 1"
    r = conn.execute(q, (owner_id, kind) if kind else (owner_id,)).fetchone()
    return public(db.row(r))


class JobContext:
    """What a handler gets: progress reporting (throttled DB writes) and cancellation checks."""

    def __init__(self, conn: sqlite3.Connection, job: dict, layout, settings):
        self.conn, self.job, self.layout, self.settings = conn, job, layout, settings
        self.id = int(job["id"])
        self.params = job["params"]
        self._last_write = 0.0
        self._last_cancel_check = 0.0
        self._cancel = False
        self._state = {"progress": float(job.get("progress") or 0.0), "message": "", "eta_s": None}

    def progress(self, fraction: float | None = None, message: str | None = None, eta_s: float | None = None, force: bool = False) -> None:
        changed = message is not None and message != self._state["message"]
        if fraction is not None:
            self._state["progress"] = max(0.0, min(1.0, float(fraction)))
        if message is not None:
            self._state["message"] = message
        self._state["eta_s"] = eta_s
        t = time.monotonic()
        if force or changed or t - self._last_write >= 0.5:
            self._last_write = t
            update(self.conn, self.id, progress=self._state["progress"], message=self._state["message"], eta_s=eta_s)

    def cancelled(self) -> bool:
        t = time.monotonic()
        if not self._cancel and t - self._last_cancel_check >= 0.5:
            self._last_cancel_check = t
            r = self.conn.execute("SELECT cancel_requested FROM jobs WHERE id=?", (self.id,)).fetchone()
            self._cancel = bool(r and r[0])
        return self._cancel

    def check_cancel(self) -> None:
        if self.cancelled():
            raise JobCancelled()

    def estimate(self, expected_s: float, message: str, start: float, end: float):
        """Context manager: while a step without its own progress runs, advance the bar along the expected time."""
        return _Estimate(self, expected_s, message, start, end)


class _Estimate:
    def __init__(self, ctx: JobContext, expected_s: float, message: str, start: float, end: float):
        import threading

        self.ctx, self.expected, self.message, self.start, self.end = ctx, max(1.0, float(expected_s)), message, start, end
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.elapsed = 0.0

    def __enter__(self):
        # the heartbeat thread has its own connection (sqlite connections are not shared across threads here)
        self._conn = db.connect(self.ctx.layout.db)
        self._t0 = time.monotonic()
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(1.0):
            el = time.monotonic() - self._t0
            # approach 95 % of the step along the expected time, then creep (never claims to be done early)
            f = min(el / self.expected, 1.0) * 0.95 + (1 - 1 / (1 + max(0.0, el - self.expected) / self.expected)) * 0.04
            remaining = max(0.0, self.expected - el)
            msg = self.message if remaining > 0 else self.message + " (예상보다 조금 더 걸리고 있어요)"
            try:
                update(self._conn, self.ctx.id, progress=self.start + (self.end - self.start) * f, message=msg, eta_s=remaining or None)
            except sqlite3.Error:
                pass

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)
        self.elapsed = time.monotonic() - self._t0
        self._conn.close()
        return False
