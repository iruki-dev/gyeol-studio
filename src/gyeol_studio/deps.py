"""Shared request state and helpers for the routers."""

from __future__ import annotations

import threading

from fastapi import Request

from . import db
from .messages import API
from .settings import Layout, Settings


class ApiError(Exception):
    def __init__(self, code: str, status: int = 400, message: str | None = None, detail: str = ""):
        super().__init__(code)
        self.code, self.status, self.message, self.detail = code, status, message or API.get(code, code), detail


class State:
    def __init__(self, settings: Settings, layout: Layout, https_info: dict):
        self.settings = settings
        self.layout = layout
        self.https_info = https_info
        self.workers = None
        self._local = threading.local()

    def conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._local.conn = db.connect(self.layout.db)
        return c


def state(request: Request) -> State:
    return request.app.state.studio


def conn(request: Request):
    return state(request).conn()


def user_id_of(request: Request) -> str | None:
    return request.headers.get("X-User") or request.query_params.get("user") or None


def current_user(request: Request) -> dict:
    uid = user_id_of(request)
    if not uid:
        raise ApiError("no_user", 401)
    u = db.row(conn(request).execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone(), ("voice_range", "onboarding"))
    if u is None:
        raise ApiError("no_user", 401)
    return u


def optional_user(request: Request) -> dict | None:
    try:
        return current_user(request)
    except ApiError:
        return None


def get_or_404(c, table: str, id_: str, json_fields: tuple[str, ...] = ()) -> dict:
    r = db.row(c.execute(f"SELECT * FROM {table} WHERE id=?", (id_,)).fetchone(), json_fields)
    if r is None:
        raise ApiError("not_found", 404)
    return r


def is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost", "testclient")
