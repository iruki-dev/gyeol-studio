"""Exports: start an export job, list finished exports, open the folder (on the PC) or download a zip."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .. import exporting, jobs
from ..deps import ApiError, conn, current_user, is_local, state

router = APIRouter(prefix="/api")


@router.post("/exports")
def start_export(request: Request, body: dict = Body(...)):
    c = conn(request)
    user = current_user(request)
    kind, scope = body.get("kind"), body.get("scope", "all")
    if kind not in (exporting.EVAL, exporting.TRAIN) or scope not in exporting.SCOPES:
        raise ApiError("bad_settings", message="내보내기 종류와 범위를 다시 골라 주세요.")
    title = {"eval": "평가용 내보내기", "train": "학습용 내보내기"}[kind]
    jid = jobs.submit(c, "export_data", {"kind": kind, "scope": scope}, title=title, owner_id=f"export:{kind}", user_id=user["id"])
    return {"job": jobs.get(c, jid)}


@router.get("/exports")
def list_exports(request: Request):
    st = state(request)
    c = conn(request)
    preview = {s: {"eval": len(exporting.eligible_takes(c, s)), "train": len(exporting.eligible_takes(c, s, labelled_only=True))}
               for s in exporting.SCOPES}
    return {"exports": exporting.list_exports(st.layout), "eligible": preview, "local": is_local(request)}


def _export_dir(request: Request, name: str) -> Path:
    st = state(request)
    d = (st.layout.exports / name).resolve()
    if d.parent != st.layout.exports.resolve() or not (d / "export.json").is_file():
        raise ApiError("not_found", 404)
    return d


@router.post("/exports/{name}/open")
def open_folder(request: Request, name: str):
    if not is_local(request):
        raise ApiError("local_only", 403)
    d = _export_dir(request, name)
    if sys.platform == "win32":
        os.startfile(str(d))  # noqa: S606 - opens the user's own export folder in Explorer
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(d)])  # noqa: S603,S607
    return {"ok": True}


@router.get("/exports/{name}/zip")
def download_zip(request: Request, name: str):
    import shutil

    d = _export_dir(request, name)
    tmp = Path(tempfile.mkdtemp(prefix="gyeol-export-"))
    z = shutil.make_archive(str(tmp / name), "zip", root_dir=d)
    return FileResponse(z, media_type="application/zip", filename=f"{name}.zip",
                        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))


@router.delete("/exports/{name}")
def delete_export(request: Request, name: str):
    import shutil

    shutil.rmtree(_export_dir(request, name), ignore_errors=True)
    return {"deleted": True}
