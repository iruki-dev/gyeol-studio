"""Status, jobs, model weights and settings."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Body, Request

from .. import __version__, coaching, db, jobs, weights
from ..deps import ApiError, conn, is_local, state, user_id_of
from ..settings import Advanced, default_data_dir, save_settings

router = APIRouter(prefix="/api")


@router.get("/status")
def status(request: Request):
    st = state(request)
    c = conn(request)
    w = [weights.status(n) for n in weights.REQUIRED]
    fetch = jobs.latest_for(c, weights.SEPARATION, "fetch_weights")
    ts = coaching.thresholds()
    return {
        "version": __version__,
        "weights": w,
        "weights_ready": all(x["present"] for x in w),
        "fetch_job": fetch,
        "setup_seen": bool(db.get_state(c, "setup_seen", False)),
        "data_dir": str(st.layout.root),
        "local": is_local(request),
        "https": st.https_info,
        "workers": st.workers.alive() if st.workers else {},
        "thresholds": {"synthetic": bool(ts.provenance.get("synthetic")), "data": ts.provenance.get("data", "")},
        "users": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
    }


@router.post("/setup/seen")
def setup_seen(request: Request):
    db.set_state(conn(request), "setup_seen", True)
    return {"ok": True}


@router.post("/weights/fetch")
def fetch_weights(request: Request):
    c = conn(request)
    if weights.status(weights.SEPARATION)["present"]:
        return {"job": None, "present": True}
    jid = jobs.submit(c, "fetch_weights", {"name": weights.SEPARATION}, title="보컬 분리 모델 받기", owner_id=weights.SEPARATION)
    return {"job": jobs.get(c, jid)}


@router.get("/jobs")
def list_jobs(request: Request, mine: bool = True):
    return {"jobs": jobs.active(conn(request), user_id_of(request) if mine else None)}


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: int):
    j = jobs.get(conn(request), job_id)
    if j is None:
        raise ApiError("not_found", 404)
    return j


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: int):
    c = conn(request)
    j = jobs.get(c, job_id)
    if j is None:
        raise ApiError("not_found", 404)
    if j["status"] not in ("queued", "running", "paused"):
        raise ApiError("job_not_cancellable")
    if j["status"] == "paused":
        jobs.mark(c, job_id, "cancelled", "취소했어요")
        return jobs.get(c, job_id)
    return jobs.request_cancel(c, job_id)


@router.post("/jobs/{job_id}/retry")
def retry_job(request: Request, job_id: int):
    c = conn(request)
    j = jobs.get(c, job_id)
    if j is None:
        raise ApiError("not_found", 404)
    if j["status"] not in ("failed", "cancelled", "paused"):
        raise ApiError("job_not_cancellable", message="이 작업은 지금 다시 시작할 수 없어요.")
    jobs.requeue(c, job_id)
    return jobs.get(c, job_id)


# ---------------------------------------------------------------- settings


def _settings_view(request: Request) -> dict:
    st = state(request)
    s = st.settings
    total, used, free = shutil.disk_usage(st.layout.root)
    return {
        **s.to_dict(),
        "cpu_count": os.cpu_count(),
        "effective_threads": s.cpu_threads(),
        "default_data_dir": str(default_data_dir()),
        "disk_free_gb": round(free / 1e9, 1),
        "weights_dir": str(weights.cache_dir()),
        "pending_restart": bool(getattr(st, "pending_restart", False)),
        "local": is_local(request),
    }


@router.get("/settings")
def get_settings(request: Request):
    return _settings_view(request)


@router.patch("/settings")
def patch_settings(request: Request, body: dict = Body(...)):
    st = state(request)
    s = st.settings
    if "threads" in body:
        t = int(body["threads"])
        if t < 0 or t > 256:
            raise ApiError("bad_settings")
        s.threads = t
        st.pending_restart = True  # workers read thread counts at start
    if "lan" in body:
        s.lan = bool(body["lan"])
        st.pending_restart = True
    if "advanced" in body:
        adv = body["advanced"] or {}
        cur = s.advanced
        for k, v in adv.items():
            if k not in Advanced.__dataclass_fields__:
                continue
            typ = type(getattr(cur, k))
            try:
                setattr(cur, k, typ(v))
            except (TypeError, ValueError) as exc:
                raise ApiError("bad_settings") from exc
        if cur.coach_level not in ("beginner", "intermediate", "advanced") or not 0 <= cur.count_in_beats <= 8 \
                or not 0 <= cur.preroll_s <= 6 or not 1 <= cur.max_session_takes <= 10:
            raise ApiError("bad_settings")
    if "data_dir" in body and body["data_dir"] != s.data_dir:
        new = Path(str(body["data_dir"])).expanduser()
        if not new.is_absolute():
            raise ApiError("data_dir_unusable", message="전체 경로로 입력해 주세요. 예: C:\\Users\\이름\\Documents\\gyeol-studio")
        try:
            new.mkdir(parents=True, exist_ok=True)
            probe = new / ".write-test"
            probe.write_text("ok")
            probe.unlink()
        except OSError as exc:
            raise ApiError("data_dir_unusable", detail=str(exc)) from exc
        move = bool(body.get("move"))
        if move:
            _move_data(st.layout.root, new)
        s.data_dir = str(new)
        st.pending_restart = True
    save_settings(s)
    return _settings_view(request)


def _move_data(old: Path, new: Path) -> None:
    if any(new.iterdir()):
        raise ApiError("data_dir_unusable", message="옮길 폴더가 비어 있지 않아요. 빈 폴더를 골라 주세요.")
    for item in old.iterdir():
        dest = new / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)


@router.post("/settings/pick-folder")
def pick_folder(request: Request):
    """Native folder picker on the PC running the app (when Tk is available)."""
    if not is_local(request):
        raise ApiError("local_only", 403)
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError:
        return {"path": None, "available": False}
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askdirectory(title="데이터 폴더 고르기")
    root.destroy()
    return {"path": path or None, "available": True}


@router.post("/restart")
def restart(request: Request):
    """Ask the launcher to restart the server (after a settings change)."""
    st = state(request)
    hook = getattr(st, "restart_hook", None)
    if hook is None:
        return {"ok": False}
    hook()
    return {"ok": True}
