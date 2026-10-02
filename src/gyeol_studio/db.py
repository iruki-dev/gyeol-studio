"""SQLite storage: people, songs, phrases, takes, analyses, feedback, labels, checks, training runs and jobs.

Audio stays in files under the data folder; the database holds paths.  The
analysis documents written by ``gyeol.api.to_json`` are stored verbatim in
``analyses.json`` together with their ``schema`` and ``version`` tags.

The server and the worker processes share the file, so the database runs in
WAL mode with a busy timeout.  The schema is versioned with ``PRAGMA user_version``.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = [
    # v1
    """
    CREATE TABLE users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        created_at REAL NOT NULL,
        level TEXT NOT NULL DEFAULT 'beginner',
        consent_analysis INTEGER NOT NULL DEFAULT 0,
        consent_training INTEGER NOT NULL DEFAULT 0,
        consent_commercial INTEGER NOT NULL DEFAULT 0,
        consent_at REAL,
        consent_version TEXT,
        retention_days INTEGER NOT NULL DEFAULT 0,
        voice_range TEXT,
        onboarding TEXT
    );
    CREATE TABLE consents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        analysis INTEGER NOT NULL, training INTEGER NOT NULL, commercial INTEGER NOT NULL,
        retention_days INTEGER NOT NULL,
        text_version TEXT NOT NULL,
        at REAL NOT NULL
    );
    CREATE TABLE songs (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        artist TEXT NOT NULL DEFAULT '',
        song_key TEXT NOT NULL DEFAULT '',
        original_name TEXT NOT NULL,
        original_path TEXT NOT NULL,
        duration_s REAL NOT NULL,
        sr INTEGER NOT NULL,
        vocal_only INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        error TEXT,
        separation TEXT,
        created_by TEXT,
        created_at REAL NOT NULL
    );
    CREATE TABLE phrases (
        id TEXT PRIMARY KEY,
        song_id TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
        name TEXT NOT NULL DEFAULT '',
        start_s REAL NOT NULL,
        end_s REAL NOT NULL,
        lyrics TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        error TEXT,
        target_analysis_id TEXT,
        note_cents TEXT,
        slice_start_s REAL,
        created_by TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE TABLE analyses (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        schema TEXT NOT NULL,
        version INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'ok',
        reason TEXT,
        json TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE INDEX analyses_owner ON analyses(owner_id);
    CREATE TABLE takes (
        id TEXT PRIMARY KEY,
        phrase_id TEXT NOT NULL REFERENCES phrases(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind TEXT NOT NULL DEFAULT 'practice',
        audio_path TEXT NOT NULL,
        sr INTEGER NOT NULL,
        duration_s REAL NOT NULL,
        created_at REAL NOT NULL,
        session_key TEXT NOT NULL,
        latency_ms REAL,
        latency_method TEXT,
        conditions TEXT,
        consent_analysis INTEGER NOT NULL,
        consent_training INTEGER NOT NULL,
        consent_commercial INTEGER NOT NULL,
        consent_at REAL,
        retain_until REAL,
        status TEXT NOT NULL,
        error TEXT,
        analysis_id TEXT,
        voiced_s REAL,
        metrics TEXT,
        pair_id TEXT,
        pair_role TEXT,
        technique TEXT
    );
    CREATE INDEX takes_phrase_user ON takes(phrase_id, user_id, created_at);
    CREATE TABLE feedback (
        id TEXT PRIMARY KEY,
        take_id TEXT NOT NULL UNIQUE REFERENCES takes(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL,
        explanation_id TEXT,
        coaching TEXT NOT NULL,
        evidence TEXT,
        noticed TEXT,
        noticed_at REAL,
        created_at REAL NOT NULL
    );
    CREATE TABLE feedback_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feedback_id TEXT NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
        take_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        item_key TEXT NOT NULL,
        response TEXT NOT NULL,
        created_at REAL NOT NULL,
        UNIQUE(feedback_id, item_key)
    );
    CREATE TABLE demos (
        id TEXT PRIMARY KEY,
        take_id TEXT NOT NULL REFERENCES takes(id) ON DELETE CASCADE,
        item_key TEXT NOT NULL,
        status TEXT NOT NULL,
        error TEXT,
        dir TEXT,
        files TEXT,
        meta TEXT,
        created_at REAL NOT NULL,
        UNIQUE(take_id, item_key)
    );
    CREATE TABLE labels (
        take_id TEXT PRIMARY KEY REFERENCES takes(id) ON DELETE CASCADE,
        register TEXT,
        qualities TEXT,
        rhythm TEXT,
        memo TEXT NOT NULL DEFAULT '',
        labeled_by TEXT,
        updated_at REAL NOT NULL
    );
    CREATE TABLE checks (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at REAL NOT NULL,
        status TEXT NOT NULL,
        trials TEXT NOT NULL,
        profile TEXT,
        summary TEXT
    );
    CREATE TABLE training_runs (
        id TEXT PRIMARY KEY,
        created_at REAL NOT NULL,
        scope TEXT NOT NULL,
        status TEXT NOT NULL,
        job_id INTEGER,
        out_dir TEXT NOT NULL,
        data_summary TEXT,
        report TEXT,
        progress TEXT,
        applied_at REAL
    );
    CREATE TABLE app_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        pool TEXT NOT NULL,
        params TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        owner_id TEXT,
        user_id TEXT,
        status TEXT NOT NULL,
        progress REAL NOT NULL DEFAULT 0,
        eta_s REAL,
        message TEXT NOT NULL DEFAULT '',
        result TEXT,
        error TEXT,
        error_detail TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        worker_pid INTEGER,
        created_at REAL NOT NULL,
        started_at REAL,
        updated_at REAL NOT NULL,
        finished_at REAL
    );
    CREATE INDEX jobs_status ON jobs(status, pool, id);
    CREATE TABLE deletion_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        deleted_at REAL NOT NULL,
        counts TEXT NOT NULL
    );
    """,
]


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def now() -> float:
    return time.time()


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, script in enumerate(SCHEMA[v:], start=v + 1):
        conn.executescript("BEGIN;" + script + f"PRAGMA user_version={i};COMMIT;")


def open_db(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    migrate(conn)
    return conn


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """A write transaction (BEGIN IMMEDIATE, so concurrent writers queue instead of failing)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def row(r: sqlite3.Row | None, json_fields: tuple[str, ...] = ()) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in json_fields:
        if d.get(k) is not None:
            d[k] = json.loads(d[k])
    return d


def rows(rs, json_fields: tuple[str, ...] = ()) -> list[dict]:
    return [row(r, json_fields) for r in rs]


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=_default)


def _default(o):
    try:
        import numpy as np

        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:  # pragma: no cover
        pass
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def get_state(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    r = conn.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r else default


def set_state(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute("INSERT INTO app_state(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, dumps(value)))


def store_analysis(conn: sqlite3.Connection, kind: str, owner_id: str, doc_json: str, status: str = "ok", reason: str = "") -> str:
    """Store a gyeol JSON document verbatim with its schema/version tags; returns the analysis id."""
    doc = json.loads(doc_json)
    aid = new_id()
    conn.execute("INSERT INTO analyses(id, kind, owner_id, schema, version, status, reason, json, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                 (aid, kind, owner_id, doc.get("schema", "?"), int(doc.get("version", 0)), status, reason, doc_json, now()))
    return aid


def load_analysis_json(conn: sqlite3.Connection, analysis_id: str) -> str | None:
    r = conn.execute("SELECT json FROM analyses WHERE id=?", (analysis_id,)).fetchone()
    return r[0] if r else None
