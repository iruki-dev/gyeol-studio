"""Training management: start a run on the chosen data scope, stop/resume, compare with the current model, apply or roll back."""

from __future__ import annotations

import json
import shutil

from fastapi import APIRouter, Body, Request

from .. import db, exporting, jobs, training
from ..deps import ApiError, conn, current_user, get_or_404, state

router = APIRouter(prefix="/api/training")


def _run_view(c, r: dict, layout) -> dict:
    out = {k: r[k] for k in ("id", "created_at", "scope", "status", "job_id", "applied_at")}
    for k in ("data_summary", "report", "progress"):
        out[k] = json.loads(r[k]) if r.get(k) else None
    out["job"] = jobs.get(c, r["job_id"]) if r.get("job_id") else None
    d = training.run_dir(layout, r["id"])
    out["has_checkpoint"] = (d / "out" / "best.pt").exists()
    out["data_removed"] = not (d / "data").exists() and out["status"] == "done"
    rep = out["report"] or {}
    prov = rep.get("provenance")
    if prov:  # the report lists source names; add what gyeol's asset list says about each (license, source)
        from ..weights import describe

        prov = {**prov, "sources_info": [describe(n) if isinstance(n, str) else n for n in prov.get("sources", [])]}
    out["provenance"] = prov
    # scores on the held-out singers: accuracies after gyeol's calibration (finalize), else the raw test pass; plus the test loss
    fin, test = rep.get("finalize") or {}, rep.get("test") or {}
    metrics = {f"test_{k}": v for k, v in test.items() if k in ("register_acc", "phonation_acc", "loss")}
    metrics.update({k: v for k, v in fin.items() if k.startswith("test_")})
    order = list(training.METRIC_LABEL)
    out["metrics"] = dict(sorted(((k, v) for k, v in metrics.items() if isinstance(v, (int, float))),
                                 key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order)))
    out["preset"] = (out["progress"] or {}).get("preset")
    return out


def _eligible(c) -> dict:
    out = {}
    for scope in exporting.SCOPES:
        takes = exporting.eligible_takes(c, scope, labelled_only=True)
        out[scope] = {"takes": len(takes), "users": len({t["user_id"] for t in takes}), "pairs": len({t["pair_id"] for t in takes if t["pair_id"]})}
    return out


@router.get("")
def overview(request: Request):
    st, c = state(request), conn(request)
    runs = [_run_view(c, db.row(r), st.layout) for r in c.execute("SELECT * FROM training_runs ORDER BY created_at DESC").fetchall()]
    return {"runs": runs, "eligible": _eligible(c), "min_singers": training.MIN_SINGERS,
            "presets": {k: v["label"] for k, v in training.PRESETS.items()}, "active": db.get_state(c, "active_model"),
            "history": db.get_state(c, "model_history", []), "metric_labels": training.METRIC_LABEL}


@router.post("/runs")
def start(request: Request, body: dict = Body(...)):
    st, c = state(request), conn(request)
    user = current_user(request)
    scope, preset = body.get("scope", "all"), body.get("preset", "quick")
    if scope not in exporting.SCOPES or preset not in training.PRESETS:
        raise ApiError("bad_settings", message="학습 데이터 범위와 방식을 다시 골라 주세요.")
    if c.execute("SELECT 1 FROM training_runs WHERE status IN ('queued','running')").fetchone():
        raise ApiError("training_running", 409)
    el = _eligible(c)[scope]
    if el["users"] < training.MIN_SINGERS:
        raise ApiError("no_training_data", message=f"학습하려면 발성·음질 라벨을 붙인 녹음이 {training.MIN_SINGERS}명 이상 필요해요. "
                                                   f"지금 이 범위에는 {el['users']}명({el['takes']}개 녹음)이에요.")
    rid = db.new_id()
    training.run_dir(st.layout, rid).mkdir(parents=True, exist_ok=True)
    c.execute("INSERT INTO training_runs(id, created_at, scope, status, out_dir, progress) VALUES(?,?,?,?,?,?)",
              (rid, db.now(), scope, "queued", str(training.run_dir(st.layout, rid).relative_to(st.layout.root)),
               db.dumps({"history": [], "log": [], "preset": preset})))
    title = {"all": "모델 학습 (전체 데이터)", "commercial": "모델 학습 (상업 이용 가능한 데이터만)"}[scope]
    jid = jobs.submit(c, "train", {"run_id": rid, "preset": preset}, title=title, owner_id=rid, user_id=user["id"], dedupe=False)
    c.execute("UPDATE training_runs SET job_id=? WHERE id=?", (jid, rid))
    return _run_view(c, get_or_404(c, "training_runs", rid), st.layout)


@router.post("/runs/{rid}/stop")
def stop(request: Request, rid: str):
    st, c = state(request), conn(request)
    r = get_or_404(c, "training_runs", rid)
    if r["job_id"]:
        jobs.request_cancel(c, r["job_id"])
        j = jobs.get(c, r["job_id"])
        if j and j["status"] == "cancelled":  # it had not started yet
            c.execute("UPDATE training_runs SET status='paused' WHERE id=?", (rid,))
            jobs.mark(c, r["job_id"], "paused", "멈췄어요")
    return _run_view(c, get_or_404(c, "training_runs", rid), st.layout)


@router.post("/runs/{rid}/resume")
def resume(request: Request, rid: str):
    st, c = state(request), conn(request)
    r = get_or_404(c, "training_runs", rid)
    if r["status"] not in ("paused", "failed"):
        raise ApiError("job_not_cancellable", message="멈춘 학습만 이어서 할 수 있어요.")
    if c.execute("SELECT 1 FROM training_runs WHERE status IN ('queued','running') AND id<>?", (rid,)).fetchone():
        raise ApiError("training_running", 409)
    c.execute("UPDATE training_runs SET status='queued' WHERE id=?", (rid,))
    jobs.requeue(c, r["job_id"])
    return _run_view(c, get_or_404(c, "training_runs", rid), st.layout)


@router.delete("/runs/{rid}")
def delete(request: Request, rid: str):
    st, c = state(request), conn(request)
    r = get_or_404(c, "training_runs", rid)
    if r["status"] in ("queued", "running"):
        raise ApiError("training_running", 409, message="학습 중인 실행은 멈춘 뒤에 지울 수 있어요.")
    if db.get_state(c, "active_model") == rid:
        raise ApiError("bad_settings", message="지금 적용된 모델은 지울 수 없어요. 다른 모델로 바꾸거나 되돌린 뒤에 지워 주세요.")
    shutil.rmtree(training.run_dir(st.layout, rid), ignore_errors=True)
    c.execute("DELETE FROM training_runs WHERE id=?", (rid,))
    return {"deleted": True}


@router.post("/runs/{rid}/apply")
def apply(request: Request, rid: str):
    st, c = state(request), conn(request)
    r = get_or_404(c, "training_runs", rid)
    if r["status"] != "done" or not (training.run_dir(st.layout, rid) / "out" / "best.pt").exists():
        raise ApiError("bad_settings", message="학습이 끝나고 평가까지 마친 모델만 적용할 수 있어요.")
    prev = db.get_state(c, "active_model")
    with db.tx(c):
        hist = db.get_state(c, "model_history", [])
        if prev and prev != rid:
            hist.append(prev)
        db.set_state(c, "model_history", hist[-20:])
        db.set_state(c, "active_model", rid)
        c.execute("UPDATE training_runs SET applied_at=? WHERE id=?", (db.now(), rid))
    return overview(request)


@router.post("/rollback")
def rollback(request: Request):
    c = conn(request)
    with db.tx(c):
        hist = db.get_state(c, "model_history", [])
        prev = hist.pop() if hist else None
        db.set_state(c, "model_history", hist)
        db.set_state(c, "active_model", prev)  # None: back to gyeol's built-in analysis (no trained heads)
    return overview(request)
