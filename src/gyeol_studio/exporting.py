"""Exports in gyeol's file formats.

* **평가용** — a folder for ``gyeol eval realset`` (``gyeol.eval.realset``): ``manifest.jsonl`` with one target
  line per phrase (the separated guide vocal, ``role: target``) and one line per take (``role: user``) with
  singer, session, condition, lyrics, the rhythm annotation from labels and the recording conditions.
* **학습용** — ``recordings.json`` as read by gyeol's own-recordings adapter (``gyeol.data.adapters.scan_own``:
  ``path``, ``user_id``, ``labels``, ``pair_id``/``pair_role``, ``session``, ``device``), plus ``manifest.json``
  in gyeol's manifest format (``dataset: own_recordings``) for ``gyeol prepare`` / ``gyeol train``.

Only takes whose owner consented to training are exported; with scope ``commercial`` only those with
commercial-training consent.  People appear under their random user id, never their name.  ``export.json``
lists what went in (including user ids, so deleting a person can remove the folders that hold their voice).
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

from . import audio, db, labels

EVAL, TRAIN = "eval", "train"
SCOPES = ("all", "commercial")


def eligible_takes(conn, scope: str, *, labelled_only: bool = False) -> list[dict]:
    q = ("SELECT t.*, p.lyrics, p.start_s, p.end_s, p.slice_start_s, p.song_id, s.vocal_only, s.title AS song_title FROM takes t "
         "JOIN phrases p ON p.id=t.phrase_id JOIN songs s ON s.id=p.song_id JOIN users u ON u.id=t.user_id "
         "WHERE t.consent_training=1 AND u.consent_training=1")
    if scope == "commercial":
        q += " AND t.consent_commercial=1 AND u.consent_commercial=1"
    if labelled_only:
        q += " AND EXISTS (SELECT 1 FROM labels l WHERE l.take_id=t.id AND (l.register IS NOT NULL OR l.qualities IS NOT NULL))"
    out = db.rows(conn.execute(q + " ORDER BY t.created_at").fetchall(), ("conditions",))
    for t in out:
        lab = conn.execute("SELECT * FROM labels WHERE take_id=?", (t["id"],)).fetchone()
        t["label"] = None if lab is None else {"register": lab["register"], "qualities": json.loads(lab["qualities"]) if lab["qualities"] else None,
                                               "rhythm": lab["rhythm"], "memo": lab["memo"]}
    return out


def _condition(t: dict) -> str:
    c = t.get("conditions") or {}
    return "mixture_phone" if c.get("earphone") == "speaker" and c.get("backing", "on") == "on" else "clean"


def _out_dir(layout, kind: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = layout.exports / f"{stamp}-{kind}"
    d.mkdir(parents=True, exist_ok=False)
    return d


def export_eval(conn, layout, scope: str, progress=lambda f, m: None) -> dict:
    from .tasks.takes import backing_segment, guide_segment

    takes = eligible_takes(conn, scope)
    d = _out_dir(layout, EVAL)
    (d / "audio" / "users").mkdir(parents=True)
    (d / "audio" / "targets").mkdir(parents=True)
    (d / "backing").mkdir()
    lines, phrases_done, users = [], set(), set()
    for i, t in enumerate(takes):
        progress(i / max(1, len(takes)), f"녹음 {i + 1}/{len(takes)} 정리하는 중")
        pid = t["phrase_id"]
        if pid not in phrases_done:
            ph = db.row(conn.execute("SELECT * FROM phrases WHERE id=?", (pid,)).fetchone())
            g, gsr = guide_segment(layout, ph)
            audio.write(d / "audio" / "targets" / f"{pid}.wav", g, gsr)
            audio.write(d / "backing" / f"{pid}.wav", backing_segment(layout, ph, gsr), gsr)
            lines.append({"id": pid, "audio": f"audio/targets/{pid}.wav", "role": "target", "condition": "clean" if t["vocal_only"] else "separated",
                          "lyrics": t["lyrics"] or None, "studio": {"song": t["song_title"], "start_s": t["start_s"], "end_s": t["end_s"]}})
            phrases_done.add(pid)
        shutil.copyfile(layout.root / t["audio_path"], d / "audio" / "users" / f"{t['id']}.wav")
        cond = t.get("conditions") or {}
        ann = {}
        if t["label"] and t["label"].get("rhythm"):
            ann["rhythm_ok"] = t["label"]["rhythm"] == "ok"
        rec = {k: v for k, v in {"device": cond.get("device"), "route": cond.get("earphone"), "room": cond.get("place"),
                                 "backing": f"backing/{pid}.wav" if cond.get("backing", "on") == "on" else None}.items() if v}
        lines.append({"id": t["id"], "audio": f"audio/users/{t['id']}.wav", "role": "user", "target": pid, "singer": t["user_id"],
                      "session": t["session_key"], "condition": _condition(t), "lyrics": t["lyrics"] or None, "annotations": ann, "recording": rec,
                      "studio": {"labels": labels.to_gyeol(t["label"]), "latency_ms": t["latency_ms"], "kind": t["kind"], "pair_id": t["pair_id"],
                                 "pair_role": t["pair_role"], "consent": {"training": True, "commercial": bool(t["consent_commercial"])}}})
        users.add(t["user_id"])
    (d / "manifest.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8")
    summary = {"kind": EVAL, "scope": scope, "created_at": db.now(), "takes": len(takes), "targets": len(phrases_done), "users": sorted(users),
               "files": ["manifest.jsonl"]}
    _finish(d, summary, "평가용 데이터 (gyeol eval realset 형식)",
            f"gyeol eval realset \"{d}\" --split held_out\n")
    return {**summary, "dir": str(d)}


def export_train(conn, layout, scope: str, progress=lambda f, m: None, out_dir: Path | None = None) -> dict:
    """Training export; ``out_dir`` (a training run's own data folder) instead of a new folder under exports/."""
    takes = eligible_takes(conn, scope, labelled_only=True)
    if out_dir is None:
        d = _out_dir(layout, TRAIN)
    else:
        d = Path(out_dir)
        d.mkdir(parents=True, exist_ok=True)
    (d / "audio").mkdir(exist_ok=True)
    entries, items, users = [], [], set()
    for i, t in enumerate(takes):
        progress(i / max(1, len(takes)), f"녹음 {i + 1}/{len(takes)} 정리하는 중")
        rel = f"audio/{t['id']}.wav"
        shutil.copyfile(layout.root / t["audio_path"], d / rel)
        lab = labels.to_gyeol(t["label"])
        cond = t.get("conditions") or {}
        e = {"path": rel, "user_id": t["user_id"], "labels": lab, "session": t["session_key"]}
        if cond.get("device"):
            e["device"] = cond["device"]
        if t["pair_id"]:
            e["pair_id"], e["pair_role"] = t["pair_id"], t["pair_role"]
        entries.append(e)
        items.append({"path": rel, "singer": t["user_id"], "labels": lab,
                      "meta": {k: e[k] for k in ("pair_id", "pair_role", "session", "device") if k in e}})
        users.add(t["user_id"])
    (d / "recordings.json").write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps({"dataset": "own_recordings", "root": str(d), "items": items}, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    counts: dict[str, int] = {}
    for it in items:
        for k in ("register", "phonation"):
            if k in it["labels"]:
                v = it["labels"][k] or "none"
                counts[f"{k}:{v}"] = counts.get(f"{k}:{v}", 0) + 1
    summary = {"kind": TRAIN, "scope": scope, "created_at": db.now(), "takes": len(takes), "users": sorted(users),
               "pairs": len({t["pair_id"] for t in takes if t["pair_id"]}), "label_counts": counts, "files": ["recordings.json", "manifest.json"]}
    _finish(d, summary, "학습용 데이터 (recordings.json + gyeol manifest)",
            f"gyeol prepare --manifest \"{d / 'manifest.json'}\" --out runs/cache\n")
    return {**summary, "dir": str(d)}


def _finish(d: Path, summary: dict, title: str, example: str) -> None:
    (d / "export.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    scope = "상업적 학습에 동의한 녹음만" if summary["scope"] == "commercial" else "학습에 동의한 녹음 전체"
    (d / "README.txt").write_text(
        f"{title}\n\n만든 날: {dt.datetime.fromtimestamp(summary['created_at']):%Y-%m-%d %H:%M}\n범위: {scope}\n"
        f"녹음 {summary['takes']}개, 참여자 {len(summary['users'])}명 (이름 대신 무작위 번호로 표시)\n\n"
        "이 폴더에는 참여자의 목소리가 들어 있어요. 동의 범위 밖으로 쓰거나 다른 곳에 올리지 마세요.\n"
        "참여자가 앱에서 데이터 삭제를 요청하면 이 폴더도 함께 지워져요.\n\n예시:\n" + example, encoding="utf-8")


def list_exports(layout) -> list[dict]:
    out = []
    if not layout.exports.exists():
        return out
    for d in sorted(layout.exports.iterdir(), reverse=True):
        f = d / "export.json"
        if f.is_file():
            try:
                s = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            out.append({**s, "name": d.name, "dir": str(d), "n_users": len(s.get("users", []))})
    return out


def remove_exports_with_user(layout, user_id: str) -> int:
    """Delete export folders that contain this person's recordings (called when the person's data is deleted)."""
    n = 0
    for e in list_exports(layout):
        if user_id in e.get("users", []):
            shutil.rmtree(e["dir"], ignore_errors=True)
            n += 1
    return n
