"""Worker process: takes jobs from one pool and runs their handlers.

Started by the server (``WorkerManager``) with the ``spawn`` start method, so it
works the same on Windows, macOS and in a frozen (PyInstaller) build.  The
heavy libraries (gyeol, torch) are imported only when a job needs them.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
import traceback

from . import db, jobs
from .messages import korean_reason
from .settings import Layout, load_settings


def _set_threads(n: int) -> None:
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[var] = str(n)


def _watch_parent(stop: threading.Event) -> None:
    """Exit when the app (parent process) is gone, even in the middle of a long job."""
    import multiprocessing

    parent = multiprocessing.parent_process()
    while not stop.wait(2.0):
        if parent is not None and not parent.is_alive():
            os._exit(0)


def _watch_training_stop(conn_path, job_id: int, stop: threading.Event) -> None:
    """Training stops cooperatively: a stop request becomes SIGINT, which gyeol's trainer turns into "save and stop"."""
    conn = db.connect(conn_path)
    try:
        while not stop.wait(1.0):
            r = conn.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
            if r and r[0]:
                signal.raise_signal(signal.SIGINT)
                return
    finally:
        conn.close()


def run_job(conn, job: dict, layout: Layout, settings) -> None:
    from .tasks import HANDLERS

    ctx = jobs.JobContext(conn, job, layout, settings)
    handler = HANDLERS[job["kind"]]
    stop = threading.Event()
    if job["kind"] == "train":
        threading.Thread(target=_watch_training_stop, args=(layout.db, ctx.id, stop), daemon=True).start()
    try:
        result = handler(ctx)
        if isinstance(result, tuple) and result and result[0] == "paused":
            jobs.mark(conn, ctx.id, "paused", result[1])
        else:
            jobs.finish(conn, ctx.id, result if isinstance(result, dict) else None)
    except jobs.JobCancelled:
        jobs.mark(conn, ctx.id, "cancelled", "취소했어요")
        from .tasks import on_cancelled

        on_cancelled(conn, job, layout)
    except jobs.UserError as exc:
        jobs.fail(conn, ctx.id, exc.message, exc.detail)
        from .tasks import on_failed

        on_failed(conn, job, exc.message, layout)
    except Exception as exc:  # noqa: BLE001 - every failure must reach the user as a job status
        detail = traceback.format_exc()
        msg = korean_reason(str(exc))
        jobs.fail(conn, ctx.id, msg, detail)
        from .tasks import on_failed

        on_failed(conn, job, msg, layout)
    finally:
        stop.set()


def main(pool: str, config_dir: str | None = None) -> None:
    if config_dir:
        os.environ["GYEOL_STUDIO_CONFIG"] = config_dir
    settings = load_settings()
    threads = settings.cpu_threads() if pool != "fast" else min(settings.cpu_threads(), 4)
    _set_threads(threads)
    layout = Layout(settings.data_dir)
    stop = threading.Event()
    threading.Thread(target=_watch_parent, args=(stop,), daemon=True).start()
    conn = db.open_db(layout.db)
    torch_threads_set = False
    pid = os.getpid()
    while True:
        try:
            job = jobs.claim(conn, pool, pid)
        except Exception:  # noqa: BLE001 - database busy etc.: try again
            time.sleep(1.0)
            continue
        if job is None:
            time.sleep(0.4)
            continue
        if not torch_threads_set:
            try:
                import torch

                torch.set_num_threads(threads)
            except Exception:  # noqa: BLE001
                pass
            torch_threads_set = True
        run_job(conn, job, layout, load_settings())


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1])
