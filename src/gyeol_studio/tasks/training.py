"""Training job: export the run's data, write the gyeol config, run ``gyeol.api.train`` (resumable, stoppable)."""

from __future__ import annotations

import json
import shutil

import yaml

from .. import db, exporting, training
from ..jobs import JobContext, UserError
from ..messages import korean_reason
from . import register


def _save_progress(conn, run_id: str, prog: dict) -> None:
    conn.execute("UPDATE training_runs SET progress=? WHERE id=?", (db.dumps(prog), run_id))


def train(ctx: JobContext):
    from gyeol import api

    conn, L = ctx.conn, ctx.layout
    run = db.row(conn.execute("SELECT * FROM training_runs WHERE id=?", (ctx.params["run_id"],)).fetchone(), ("data_summary", "progress"))
    if run is None:
        return {"gone": True}
    d = training.run_dir(L, run["id"])
    from gyeol.train.runner import STATE_FILE  # the file whose presence means "this run can be resumed"

    state = d / "out" / STATE_FILE
    resuming = state.exists()
    prog = run.get("progress") or {"history": [], "log": []}
    conn.execute("UPDATE training_runs SET status='running' WHERE id=?", (run["id"],))
    if not (d / "data" / "manifest.json").exists():
        ctx.progress(0.02, "학습에 쓸 녹음을 모으는 중", force=True)
        summary = exporting.export_train(conn, L, run["scope"], lambda f, m: ctx.progress(0.02 + 0.06 * f, m), out_dir=d / "data")
        if len(summary["users"]) < training.MIN_SINGERS:
            shutil.rmtree(d / "data", ignore_errors=True)
            raise UserError(f"학습하려면 라벨을 붙인 녹음이 {training.MIN_SINGERS}명 이상 필요해요. 지금은 {len(summary['users'])}명이에요.")
        conn.execute("UPDATE training_runs SET data_summary=? WHERE id=?", (db.dumps(summary), run["id"]))
    cfg = training.config(d, ctx.params.get("preset", "quick"), ctx.settings.cpu_threads())
    (d / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    n_items = len(json.loads((d / "data" / "recordings.json").read_text(encoding="utf-8")))
    ctx.progress(0.1, "녹음을 학습용으로 준비하는 중 (음 높이·특징 계산)" if not resuming else "멈춘 곳부터 이어서 학습하는 중", force=True)

    # gyeol prepares the data before its first log line; until then the bar follows an estimate (~1.5 s per recording)
    est = None if resuming else ctx.estimate(5.0 + 1.5 * n_items, "녹음을 학습용으로 준비하는 중 (음 높이·특징 계산)", 0.1, 0.12)
    if est is not None:
        est.__enter__()

    def end_estimate() -> None:
        nonlocal est
        if est is not None:
            est.__exit__(None, None, None)
            est = None

    def log(line: str) -> None:
        p = training.parse_log(line)
        if p["kind"] in ("train", "val"):
            end_estimate()
        if p["kind"] == "train":
            ctx.progress(0.12 + 0.8 * p["step"] / max(1, p["total"]), f"학습 중 ({p['step']}/{p['total']}단계)", p["eta_s"])
            prog.update(step=p["step"], total=p["total"])
        elif p["kind"] == "val":
            prog["history"].append({"step": p["step"], **p["metrics"], "best": p["best"]})
            prog["last_val"] = prog["history"][-1]
            _save_progress(conn, run["id"], prog)
        else:
            prog["log"] = (prog.get("log") or [])[-30:] + [line[:300]]

    try:
        res = api.train(str(d / "config.yaml"), resume=resuming, log=log)
    except KeyboardInterrupt:  # stopped while gyeol was still preparing data (its stop handler starts with training)
        _save_progress(conn, run["id"], prog)
        conn.execute("UPDATE training_runs SET status='paused' WHERE id=?", (run["id"],))
        return ("paused", "멈췄어요. '이어서 학습'을 누르면 준비한 데이터부터 다시 시작해요.")
    except (ValueError, FileNotFoundError) as exc:
        raise UserError(korean_reason(str(exc)) if "label" in str(exc) else "학습을 시작하지 못했어요. 라벨과 녹음이 충분한지 확인해 주세요.",
                        str(exc)) from exc
    finally:
        end_estimate()
    _save_progress(conn, run["id"], prog)
    if res.status == "interrupted":
        conn.execute("UPDATE training_runs SET status='paused' WHERE id=?", (run["id"],))
        return ("paused", f"{res.position.step}단계에서 멈췄어요. '이어서 학습'을 누르면 멈춘 곳부터 계속해요.")
    report = res.report or {}
    conn.execute("UPDATE training_runs SET status='done', report=? WHERE id=?", (db.dumps(report), run["id"]))
    return {"run_id": run["id"], "status": res.status, "steps": res.position.step}


register("train", train)
