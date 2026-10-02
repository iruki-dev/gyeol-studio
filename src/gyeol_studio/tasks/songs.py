"""Songs: model download, vocal separation (``gyeol.api.separate_target``) and phrase target analysis (``gyeol.api.analyze``)."""

from __future__ import annotations

import contextlib
import io
import threading
import time
from pathlib import Path

import numpy as np

from .. import audio, db, jobs, weights
from ..jobs import JobContext, UserError
from ..messages import korean_reason

PREROLL_MAX_S = 6.0  # phrase slices keep this much before the phrase (count-in / lead-in playback)
TAIL_MAX_S = 2.0
DEFAULT_RTF_4_THREADS = 8.0  # separation seconds per audio second on 4 CPU threads (measured: 7.5 on a 4-core VM)


# ---------------------------------------------------------------- weights


def fetch_weights(ctx: JobContext) -> dict:
    name = ctx.params.get("name", weights.SEPARATION)
    st = weights.status(name)
    if st["present"]:
        _after_weights(ctx.conn)
        return {"name": name, "already": True}
    info = weights.asset_info(name)
    expected = weights.remote_size(info["url"]) or weights.EXPECTED_SIZE.get(name)
    dest = weights.target_path(name)
    if expected and weights.free_bytes(dest.parent) < expected * 1.1:
        raise UserError("저장 공간이 부족해서 모델을 받을 수 없어요. 디스크에 1GB 이상 공간을 비운 뒤 다시 시도해 주세요.")
    weights.remove_partial(name)
    ctx.progress(0.0, "모델을 받는 중", None, force=True)
    out = io.StringIO()
    box: dict = {}

    def run() -> None:
        from gyeol.cli import main as gyeol_cli

        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                box["code"] = gyeol_cli(["fetch", name])  # downloads to <file>.part, verifies sha256, then moves into place
        except BaseException as exc:  # noqa: BLE001 - reported below
            box["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    part = weights.part_path(name)
    t0, last = time.monotonic(), (0.0, 0)
    speed = None
    while t.is_alive():
        t.join(0.5)
        size = part.stat().st_size if part.exists() else (dest.stat().st_size if dest.exists() else 0)
        now = time.monotonic()
        if now - last[0] >= 1.0:
            inst = (size - last[1]) / max(now - last[0], 1e-3)
            speed = inst if speed is None else 0.7 * speed + 0.3 * inst
            last = (now, size)
        if expected:
            frac = min(size / expected, 1.0)
            eta = (expected - size) / speed if speed and speed > 0 else None
            msg = f"모델을 받는 중 ({size / 1e6:,.0f} / {expected / 1e6:,.0f} MB)"
            if frac >= 0.999:
                msg, eta = "받은 파일을 확인하는 중", None
            ctx.progress(0.97 * frac, msg, eta)
        else:
            ctx.progress(None, f"모델을 받는 중 ({size / 1e6:,.0f} MB)", None)
    if "exc" in box:
        raise UserError(korean_reason(str(box["exc"])), out.getvalue() + f"\n{box['exc']!r}")
    code = box.get("code")
    if code == 4:
        raise UserError(korean_reason("checksum mismatch"), out.getvalue())
    if code != 0:
        raise UserError("모델을 받지 못했어요. 인터넷 연결을 확인하고 다시 시도해 주세요.", out.getvalue())
    _after_weights(ctx.conn)
    return {"name": name, "seconds": time.monotonic() - t0}


def _after_weights(conn) -> None:
    """Songs that waited for the separation model start now."""
    for r in conn.execute("SELECT id, title FROM songs WHERE status='waiting_weights'").fetchall():
        conn.execute("UPDATE songs SET status='queued', error=NULL WHERE id=?", (r["id"],))
        jobs.submit(conn, "separate_song", {"song_id": r["id"]}, title=f"보컬 분리: {r['title']}", owner_id=r["id"])


# ---------------------------------------------------------------- separation


def separation_rtf(conn, threads: int) -> float:
    v = db.get_state(conn, "separation_rtf_per_thread")
    if v:
        return float(v) / threads
    return DEFAULT_RTF_4_THREADS * 4 / threads


def separate_song(ctx: JobContext) -> dict:
    from gyeol import api

    conn, L = ctx.conn, ctx.layout
    song = db.row(conn.execute("SELECT * FROM songs WHERE id=?", (ctx.params["song_id"],)).fetchone())
    if song is None:
        return {"gone": True}
    d = L.song_dir(song["id"])
    ctx.progress(0.02, "음원 파일을 읽는 중", force=True)
    x, sr = audio.read(L.root / song["original_path"])
    if song["vocal_only"]:
        vocal, acc, meta = x, np.zeros_like(x), {"separator": "none (vocal-only upload)"}
    else:
        if not weights.status(weights.SEPARATION)["present"]:
            conn.execute("UPDATE songs SET status='waiting_weights' WHERE id=?", (song["id"],))
            jobs.submit(conn, "fetch_weights", {"name": weights.SEPARATION}, title="보컬 분리 모델 받기", owner_id=weights.SEPARATION)
            return {"waiting_weights": True}
        conn.execute("UPDATE songs SET status='separating', error=NULL WHERE id=?", (song["id"],))
        threads = ctx.settings.cpu_threads()
        expected = separation_rtf(conn, threads) * len(x) / sr + 15.0  # + model loading
        with ctx.estimate(expected, "보컬과 반주를 나누는 중", 0.05, 0.92) as est:
            r = api.separate_target(x, sr, cache_dir=L.separation_cache)
        if not r.ok:
            raise UserError(korean_reason(r.reason), r.reason)
        ts = r.value
        if ts.meta.get("cache") == "miss" and len(x) > 10 * sr:
            per_thread = est.elapsed * threads / (len(x) / sr)
            old = db.get_state(conn, "separation_rtf_per_thread")
            db.set_state(conn, "separation_rtf_per_thread", per_thread if not old else 0.5 * float(old) + 0.5 * per_thread)
        vocal, acc = np.asarray(ts.vocal, float), np.asarray(ts.accompaniment, float)
        meta = {"key": ts.key, "separator": ts.separator, **{k: v for k, v in ts.meta.items() if isinstance(v, (str, int, float, type(None)))}}
    ctx.progress(0.94, "나눈 소리를 저장하는 중", force=True)
    audio.write(d / "vocal.wav", vocal, sr)
    audio.write(d / "accompaniment.wav", acc, sr)
    conn.execute("UPDATE songs SET status='ready', error=NULL, separation=? WHERE id=?", (db.dumps(meta), song["id"]))
    for p in conn.execute("SELECT id, name FROM phrases WHERE song_id=? AND status IN ('waiting','failed','cancelled')", (song["id"],)).fetchall():
        queue_phrase(conn, p["id"], song["title"], p["name"])
    return {"song_id": song["id"], "separator": meta.get("separator")}


# ---------------------------------------------------------------- phrase target


def queue_phrase(conn, phrase_id: str, song_title: str, phrase_name: str) -> int:
    conn.execute("UPDATE phrases SET status='queued', error=NULL WHERE id=?", (phrase_id,))
    return jobs.submit(conn, "analyze_phrase", {"phrase_id": phrase_id}, title=f"목표 분석: {song_title} {phrase_name}".strip(),
                       owner_id=phrase_id)


def analyze_phrase(ctx: JobContext) -> dict:
    from gyeol import api
    from gyeol.coach import note_centres

    conn, L = ctx.conn, ctx.layout
    ph = db.row(conn.execute("SELECT * FROM phrases WHERE id=?", (ctx.params["phrase_id"],)).fetchone())
    if ph is None:
        return {"gone": True}
    song = db.row(conn.execute("SELECT * FROM songs WHERE id=?", (ph["song_id"],)).fetchone())
    if song["status"] != "ready":
        conn.execute("UPDATE phrases SET status='waiting' WHERE id=?", (ph["id"],))
        return {"waiting_song": True}
    conn.execute("UPDATE phrases SET status='analyzing', error=NULL WHERE id=?", (ph["id"],))
    ctx.progress(0.1, "목표 소리를 준비하는 중", force=True)
    sd, pd = L.song_dir(song["id"]), L.phrase_dir(ph["id"])
    vocal, sr = audio.read(sd / "vocal.wav")
    acc, _ = audio.read(sd / "accompaniment.wav")
    mix, msr = audio.read(L.root / song["original_path"])
    s0 = max(0.0, ph["start_s"] - PREROLL_MAX_S)
    e0 = min(len(vocal) / sr, ph["end_s"] + TAIL_MAX_S)
    audio.write(pd / "guide.wav", audio.segment(vocal, sr, s0, e0), sr)
    audio.write(pd / "backing.wav", audio.segment(acc, sr, s0, e0), sr)
    audio.write(pd / "mix.wav", audio.segment(mix, msr, s0, e0), msr)
    target = audio.segment(vocal, sr, ph["start_s"], ph["end_s"])
    ctx.progress(0.35, "목표 음정과 박자를 분석하는 중", force=True)
    r = api.analyze(target, sr, separation="off", lyrics=ph["lyrics"] or None, recording_id=f"phrase-{ph['id']}")
    if not r.usable:
        raise UserError("이 소절에서 노랫소리를 찾지 못했어요. 가수가 노래하는 구간으로 다시 지정해 주세요.", r.reason)
    rep = r.value
    doc = api.to_json(rep)
    ctx.progress(0.9, "결과를 저장하는 중", force=True)
    with db.tx(conn):
        aid = db.store_analysis(conn, "target", ph["id"], doc, r.status.value, r.reason)
        conn.execute("UPDATE phrases SET status='ready', error=NULL, target_analysis_id=?, note_cents=?, slice_start_s=?, updated_at=? WHERE id=?",
                     (aid, db.dumps([None if not np.isfinite(c) else c for c in note_centres(rep)]), s0, db.now(), ph["id"]))
    return {"phrase_id": ph["id"], "notes": len(rep.meta.get("notes", [])), "syllables": len(rep.meta.get("syllables", []) or [])}


def phrase_paths(layout, phrase_id: str) -> dict[str, Path]:
    d = layout.phrase_dir(phrase_id)
    return {"guide": d / "guide.wav", "backing": d / "backing.wav", "mix": d / "mix.wav"}
