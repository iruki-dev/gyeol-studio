"""Start-check scoring job."""

from __future__ import annotations

import json

from .. import checks, db
from ..jobs import JobContext, UserError
from . import register


def score_check(ctx: JobContext) -> dict:
    conn, L = ctx.conn, ctx.layout
    ch = db.row(conn.execute("SELECT * FROM checks WHERE id=?", (ctx.params["check_id"],)).fetchone(), ("trials",))
    if ch is None:
        return {"gone": True}
    data = ch["trials"]
    trials, disc = data.get("recordings", []), data.get("discrimination", [])
    if not trials and not disc:
        raise UserError("검사 녹음이 없어요. 처음부터 다시 해 주세요.")
    docs: list[str] = []
    res = checks.score(L.check_dir(ch["user_id"]) / ch["id"], trials, disc, lambda f, m: ctx.progress(0.05 + 0.85 * f, m), keep=docs.append)
    with db.tx(conn):
        for d in docs:
            db.store_analysis(conn, "check", ch["id"], d)
        conn.execute("UPDATE checks SET status='done', profile=?, summary=? WHERE id=?",
                     (db.dumps({**res["profile"], "measured": res["measured"]}), db.dumps(res["summary"]), ch["id"]))
        vr = res["profile"].get("voice_range")
        conn.execute("UPDATE users SET onboarding=?, voice_range=COALESCE(?, voice_range) WHERE id=?",
                     (db.dumps({"check_id": ch["id"], "at": ch["created_at"], **{k: res["profile"][k] for k in
                                ("production_band", "precision_band", "perception_band", "routes", "production_mae_cents",
                                 "perception_threshold_cents")}}), json.dumps(vr) if vr else None, ch["user_id"]))
    return {"check_id": ch["id"]}


register("score_check", score_check, owner_table="checks")
