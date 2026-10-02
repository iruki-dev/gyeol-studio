"""FastAPI app: the JSON API under ``/api`` and the web UI as static files.

``create_app`` wires the routers; ``WorkerManager`` starts the worker
processes (one per job pool), restarts them if they die, and kills a worker
whose running job cannot stop by itself when the user cancels it.
"""

from __future__ import annotations

import logging
import multiprocessing
import threading
import time
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, db, jobs
from .deps import ApiError, State
from .settings import Layout, Settings, config_dir

log = logging.getLogger("gyeol_studio")


class WorkerManager:
    def __init__(self, state: State, pools=jobs.POOLS):
        self.state = state
        self.pools = pools
        self.procs: dict[str, multiprocessing.Process] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._ctx = multiprocessing.get_context("spawn")
        self._thread = threading.Thread(target=self._monitor, daemon=True, name="worker-monitor")

    def start(self) -> None:
        conn = self.state.conn()
        jobs.recover(conn)
        for pool in self.pools:
            self._spawn(pool)
        self._thread.start()

    def _spawn(self, pool: str) -> None:
        from .worker import main as worker_main

        p = self._ctx.Process(target=worker_main, args=(pool, str(config_dir())), name=f"gyeol-studio-{pool}", daemon=True)
        p.start()
        self.procs[pool] = p

    def _monitor(self) -> None:
        conn = db.connect(self.state.layout.db)
        while not self._stop.wait(1.0):
            with self._lock:
                for pool, p in list(self.procs.items()):
                    if not p.is_alive() and not self._stop.is_set():
                        # a worker died (crash, out of memory): its running job fails visibly, then the worker restarts
                        for j in conn.execute("SELECT id FROM jobs WHERE status='running' AND pool=? AND worker_pid=?", (pool, p.pid)).fetchall():
                            jobs.fail(conn, j[0], "작업 중에 처리 프로그램이 멈췄어요. 다시 시도해 주세요. 계속되면 다른 프로그램을 닫고 해 보세요.",
                                      f"worker exit code {p.exitcode}")
                            self._owner_failed(conn, j[0])
                        self._spawn(pool)
                # cancel requests for jobs that cannot stop part-way: restart their worker
                for j in conn.execute("SELECT id, kind, pool, worker_pid, owner_id FROM jobs WHERE status='running' AND cancel_requested=1").fetchall():
                    if j["kind"] in jobs.NON_COOPERATIVE:
                        p = self.procs.get(j["pool"])
                        if p is not None and p.pid == j["worker_pid"] and p.is_alive():
                            p.kill()
                            p.join(5)
                        jobs.mark(conn, j["id"], "cancelled", "취소했어요")
                        from .tasks import on_cancelled

                        on_cancelled(conn, db.row(conn.execute("SELECT * FROM jobs WHERE id=?", (j["id"],)).fetchone()), self.state.layout)
                        if j["kind"] == "fetch_weights":
                            from . import weights

                            weights.remove_partial(j["owner_id"] or weights.SEPARATION)
                        self._spawn(j["pool"])
        conn.close()

    def _owner_failed(self, conn, job_id: int) -> None:
        from .tasks import on_failed

        j = db.row(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
        if j:
            on_failed(conn, j, j["error"] or "", self.state.layout)

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            for p in self.procs.values():
                if p.is_alive():
                    p.terminate()
            for p in self.procs.values():
                p.join(5)

    def alive(self) -> dict[str, bool]:
        return {k: p.is_alive() for k, p in self.procs.items()}


def web_root() -> Path:
    return Path(str(resources.files("gyeol_studio").joinpath("web")))


def create_app(settings: Settings, *, start_workers: bool = False, https_info: dict | None = None) -> FastAPI:
    layout = Layout(settings.data_dir)
    layout.ensure()
    db.open_db(layout.db).close()
    state = State(settings, layout, https_info or {})
    app = FastAPI(title="gyeol 스튜디오", version=__version__, docs_url=None, redoc_url=None)
    app.state.studio = state

    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, exc: ApiError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message, "detail": exc.detail}}, status_code=exc.status)

    @app.exception_handler(Exception)
    async def _any_error(_req: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse({"error": {"code": "internal", "message": "처리하는 중에 문제가 생겼어요. 화면을 새로 고친 뒤 다시 시도해 주세요.",
                                       "detail": f"{type(exc).__name__}: {exc}"}}, status_code=500)

    from .routes import register_routes

    register_routes(app)

    if state.https_info.get("port"):
        from fastapi.responses import RedirectResponse

        @app.middleware("http")
        async def _lan_https(request: Request, call_next):
            # phones reach the plain http port only to download the certificate; everything else goes to https
            client = request.client.host if request.client else ""
            if request.url.scheme == "http" and client not in ("127.0.0.1", "::1") and request.url.path not in ("/ca.crt",):
                host = (request.url.hostname or "").strip("[]")
                return RedirectResponse(f"https://{host}:{state.https_info['port']}{request.url.path}", status_code=307)
            if client and client not in ("127.0.0.1", "::1") and request.url.path.startswith("/api/"):
                state.devices[client] = {"seen": time.time(), "agent": request.headers.get("user-agent", "")[:200]}
            return await call_next(request)

    root = web_root()

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=root), name="static")

    if start_workers:  # tests and the launcher; the launcher starts them itself so two listeners share one set
        start_background(state)

    return app


def start_background(state: State) -> WorkerManager:
    """Start the worker processes and the retention sweep (once per app, whatever the number of listeners)."""
    from .maintenance import startup_maintenance

    manager = WorkerManager(state)
    state.workers = manager
    manager.start()
    threading.Thread(target=startup_maintenance, args=(state,), daemon=True, name="maintenance").start()
    return manager


def wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    import socket

    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


__all__ = ["WorkerManager", "create_app", "start_background", "wait_for_port"]
