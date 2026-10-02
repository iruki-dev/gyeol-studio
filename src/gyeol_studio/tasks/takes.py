"""Takes: analysis (``gyeol.api.analyze``), comparison (``compare``), coaching selection and demos (``render_demo``)."""

from __future__ import annotations

import datetime as dt
import json

import numpy as np

from .. import audio, coaching, db
from ..jobs import JobContext, UserError
from ..messages import korean_reason


def day_key(t: float) -> str:
    return dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d")


def _target(conn, phrase: dict):
    from gyeol import api

    doc = db.load_analysis_json(conn, phrase["target_analysis_id"])
    return api.from_json(doc)


def guide_segment(layout, phrase: dict) -> tuple[np.ndarray, int]:
    g, sr = audio.read(layout.phrase_dir(phrase["id"]) / "guide.wav")
    off = phrase["start_s"] - (phrase["slice_start_s"] or 0.0)
    return audio.segment(g, sr, off, off + phrase["end_s"] - phrase["start_s"]), sr


def backing_segment(layout, phrase: dict, sr_to: int) -> np.ndarray:
    b, sr = audio.read(layout.phrase_dir(phrase["id"]) / "backing.wav")
    off = phrase["start_s"] - (phrase["slice_start_s"] or 0.0)
    return audio.resample(audio.segment(b, sr, off, off + phrase["end_s"] - phrase["start_s"]), sr, sr_to)


def wellbeing(conn, user_id: str, session_key: str, created_at: float) -> dict:
    """Voiced time this session / today and the session's attempt metrics (oldest first), up to this take."""
    rs = conn.execute("SELECT created_at, session_key, voiced_s, metrics FROM takes WHERE user_id=? AND status='ready' AND created_at<=? "
                      "AND created_at>=? ORDER BY created_at", (user_id, created_at, created_at - 86400 * 2)).fetchall()
    day = day_key(created_at)
    session_s = sum(r["voiced_s"] or 0.0 for r in rs if r["session_key"] == session_key)
    day_s = sum(r["voiced_s"] or 0.0 for r in rs if day_key(r["created_at"]) == day)
    metrics = [json.loads(r["metrics"]) for r in rs if r["session_key"] == session_key and r["metrics"]]
    return {"session_s": session_s, "day_s": day_s, "metrics": metrics}


def fatigue(metrics: list[dict]) -> list[str]:
    from gyeol.coach import AttemptMetrics, fatigue_flags

    hist = [AttemptMetrics(m["instability_cents"], m["top_cents"], m["breath_db"]) for m in metrics]
    return fatigue_flags(hist)


def _voice_range(user: dict):
    from gyeol.coach import VoiceRange

    if not user.get("voice_range"):
        return None
    v = json.loads(user["voice_range"])
    try:
        return VoiceRange(v["low_cents"], v["high_cents"], v["tess_low_cents"], v["tess_high_cents"], v.get("source", "onboarding"))
    except (KeyError, ValueError):
        return None


def analyze_take(ctx: JobContext) -> dict:
    from gyeol import api
    from gyeol.coach import attempt_metrics, voiced_seconds

    conn, L, adv = ctx.conn, ctx.layout, ctx.settings.advanced
    take = db.row(conn.execute("SELECT * FROM takes WHERE id=?", (ctx.params["take_id"],)).fetchone(), ("conditions",))
    if take is None:
        return {"gone": True}
    phrase = db.row(conn.execute("SELECT * FROM phrases WHERE id=?", (take["phrase_id"],)).fetchone())
    user = db.row(conn.execute("SELECT * FROM users WHERE id=?", (take["user_id"],)).fetchone())
    if phrase["status"] != "ready":
        raise UserError("이 소절의 목표 분석이 아직 끝나지 않았어요. 잠시 후 다시 분석해 주세요.")
    conn.execute("UPDATE takes SET status='analyzing', error=NULL WHERE id=?", (take["id"],))
    ctx.progress(0.05, "녹음을 읽는 중", force=True)
    x, sr = audio.read(L.root / take["audio_path"])
    guide, gsr = guide_segment(L, phrase)
    cond = take.get("conditions") or {}
    kw: dict = {"separation": "off"}
    if cond.get("earphone") == "speaker" and cond.get("backing", "on") == "on":
        # the accompaniment came out of a speaker into the microphone: subtract the known accompaniment
        kw = {"separation": "auto", "backing": backing_segment(L, phrase, sr)}
    ctx.progress(0.12, "내 목소리를 분석하는 중", force=True)
    r = api.analyze(x, sr, reference=(guide, gsr), recording_id=take["id"], **kw)
    if not r.usable:
        raise UserError(korean_reason(r.reason), r.reason)
    rep = r.value
    voiced = voiced_seconds(rep)
    if voiced < 0.3:
        raise UserError("노래하는 목소리가 거의 들리지 않았어요. 마이크 가까이에서 다시 불러 주세요.", f"voiced {voiced:.2f} s")
    m = attempt_metrics(rep)
    metrics = {"instability_cents": m.instability_cents, "top_cents": m.top_cents, "breath_db": m.breath_db}
    metrics = {k: (float(v) if np.isfinite(v) else None) for k, v in metrics.items()}
    with db.tx(conn):
        aid = db.store_analysis(conn, "take", take["id"], api.to_json(rep), r.status.value, r.reason)
        conn.execute("UPDATE takes SET analysis_id=?, voiced_s=?, metrics=? WHERE id=?",
                     (aid, voiced, db.dumps(metrics) if all(v is not None for v in metrics.values()) else None, take["id"]))
    ctx.check_cancel()

    # takes of this practice session on this phrase: habit (same direction every time) vs one-off
    prev = conn.execute("SELECT analysis_id FROM takes WHERE phrase_id=? AND user_id=? AND session_key=? AND status='ready' AND id<>? "
                        "AND created_at<=? ORDER BY created_at DESC LIMIT ?",
                        (phrase["id"], take["user_id"], take["session_key"], take["id"], take["created_at"], max(0, adv.max_session_takes - 1))).fetchall()
    reps = [api.from_json(db.load_analysis_json(conn, p["analysis_id"])) for p in reversed(prev)] + [rep]
    target = _target(conn, phrase)
    msg = "목표와 비교하는 중" + (" (차이마다 얼마나 잘 들리는지 확인해요)" if adv.audibility else "")
    with ctx.estimate(10.0 if adv.audibility else 2.0, msg, 0.3, 0.8):
        ex = api.compare(reps, target, audibility=(x, sr) if adv.audibility else None)
    if not ex.usable:
        raise UserError("목표와 비교하지 못했어요. 소절 전체를 처음부터 끝까지 불러 주세요.", ex.reason)
    exp = ex.value
    vr = _voice_range(user)
    note_cents = [c if c is not None else float("nan") for c in json.loads(phrase["note_cents"] or "[]")]
    coach_doc = coaching.select(exp, level=user["level"] or adv.coach_level, show_unverified=adv.show_unverified_items,
                                voice_range=vr, target_note_cents=note_cents or None)
    coach_doc["compare_status"] = ex.status.value
    coach_doc["compare_reason"] = ex.reason
    wb = wellbeing(conn, take["user_id"], take["session_key"], take["created_at"])
    fat = fatigue(wb["metrics"]) if len(wb["metrics"]) else []
    coach_doc["health"] = coaching.health_notices(session_s=wb["session_s"], day_s=wb["day_s"], fatigue=fat,
                                                  phrase_check=coach_doc.get("phrase_check"))
    coach_doc["referral"] = coaching.strings()["health"]["referral"]
    ev = coaching.evidence(exp, rep, target)
    with db.tx(conn):
        eid = db.store_analysis(conn, "explanation", take["id"], api.to_json(exp), ex.status.value, ex.reason)
        fid = db.new_id()
        conn.execute("DELETE FROM feedback WHERE take_id=?", (take["id"],))
        conn.execute("INSERT INTO feedback(id, take_id, user_id, explanation_id, coaching, evidence, created_at) VALUES(?,?,?,?,?,?,?)",
                     (fid, take["id"], take["user_id"], eid, db.dumps(coach_doc), db.dumps(ev), db.now()))
        conn.execute("UPDATE takes SET status='ready', error=NULL WHERE id=?", (take["id"],))
    primary = coach_doc.get("primary")
    if primary:
        ctx.progress(0.85, "내 목소리로 시범음을 만드는 중", force=True)
        try:
            _render(conn, L, take, rep, exp, target, x, sr, primary["key"])
        except Exception as exc:  # noqa: BLE001 - the feedback is ready; the demo can be retried from the coaching screen
            msg = exc.message if isinstance(exc, UserError) else "시범음을 만들지 못했어요. '내 목소리 시범음 만들기'를 다시 눌러 주세요."
            conn.execute("UPDATE demos SET status='failed', error=? WHERE take_id=? AND item_key=?", (msg, take["id"], primary["key"]))
    return {"take_id": take["id"], "feedback_id": fid, "primary": primary["key"] if primary else None}


def _render(conn, L, take: dict, rep, exp, target, x, sr, item_key: str) -> dict:
    from gyeol import api

    slug = item_key.replace(":", "_")
    out = L.demo_dir(take["id"], slug)
    did = db.new_id()
    conn.execute("INSERT INTO demos(id, take_id, item_key, status, created_at) VALUES(?,?,?,?,?) "
                 "ON CONFLICT(take_id, item_key) DO UPDATE SET status='rendering', error=NULL", (did, take["id"], item_key, "rendering", db.now()))
    d = api.render_demo(x, sr, rep, exp, target, item=coaching.key_tuple(item_key), out_dir=out)
    if not d.ok:
        msg = korean_reason(d.reason) if "no confident" not in d.reason else "이 항목은 시범음을 만들 수 없어요."
        conn.execute("UPDATE demos SET status='failed', error=? WHERE take_id=? AND item_key=?", (msg, take["id"], item_key))
        raise UserError(msg, d.reason)
    files = {k: str(v.relative_to(L.root)) for k, v in d.value.files.items()}
    conn.execute("UPDATE demos SET status='ready', error=NULL, dir=?, files=?, meta=? WHERE take_id=? AND item_key=?",
                 (str(out.relative_to(L.root)), db.dumps(files), db.dumps(d.value.metadata), take["id"], item_key))
    return files


def render_demo(ctx: JobContext) -> dict:
    from gyeol import api

    conn, L = ctx.conn, ctx.layout
    take = db.row(conn.execute("SELECT * FROM takes WHERE id=?", (ctx.params["take_id"],)).fetchone())
    if take is None or not take["analysis_id"]:
        raise UserError("먼저 녹음 분석이 끝나야 시범음을 만들 수 있어요.")
    fb = db.row(conn.execute("SELECT * FROM feedback WHERE take_id=?", (take["id"],)).fetchone())
    phrase = db.row(conn.execute("SELECT * FROM phrases WHERE id=?", (take["phrase_id"],)).fetchone())
    ctx.progress(0.2, "내 목소리로 시범음을 만드는 중", force=True)
    x, sr = audio.read(L.root / take["audio_path"])
    rep = api.from_json(db.load_analysis_json(conn, take["analysis_id"]))
    exp = api.from_json(db.load_analysis_json(conn, fb["explanation_id"]))
    files = _render(conn, L, take, rep, exp, _target(conn, phrase), x, sr, ctx.params["item_key"])
    return {"files": files}
