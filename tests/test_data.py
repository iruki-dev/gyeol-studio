"""Phase 2: labels, consent-scoped exports in gyeol's formats (read back with gyeol's own loaders), deletion."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .conftest import SR, melody_audio, wait_job, wav_bytes


def _setup(client, users=(("가수1", True, True), ("가수2", True, False), ("가수3", False, False)), detune=0.0):
    """One song + phrase, one take per user (consents as given), all analysed."""
    ids = []
    for name, training, commercial in users:
        r = client.post("/api/users", json={"name": name, "consent": {"analysis": True, "training": training, "commercial": commercial}})
        ids.append(r.json()["id"])
    h = {"X-User": ids[0]}
    target = np.r_[np.zeros(SR // 2), melody_audio(), np.zeros(SR // 2)]
    s = client.post("/api/songs", data={"title": "곡", "vocal_only": "true"}, files={"file": ("g.wav", wav_bytes(target), "audio/wav")}, headers=h).json()
    wait_job(client, h, lambda: client.get(f"/api/songs/{s['id']}").json()["status"] == "ready")
    dur = len(target) / SR
    p = client.post(f"/api/songs/{s['id']}/phrases", json={"start_s": 0.3, "end_s": dur - 0.2, "lyrics": "사랑 해요 그대"}).json()
    wait_job(client, h, lambda: client.get(f"/api/phrases/{p['id']}").json()["status"] == "ready")
    sung = np.r_[np.zeros(SR // 2), melody_audio(detune=(0, 0, detune, 0, 0, 0), seed=5), np.zeros(SR // 2)] if detune else target
    seg = sung[int(0.3 * SR):int((dur - 0.2) * SR)]
    takes = []
    for i, uid in enumerate(ids):
        raw = np.r_[np.zeros(2 * SR), seg * (0.8 + 0.1 * i), np.zeros(SR)]
        meta = {"phrase_offset_s": 2.0, "conditions": {"device": f"폰{i}", "earphone": "wired", "backing": "on", "place": "집"}}
        t = client.post(f"/api/phrases/{p['id']}/takes", data={"meta": json.dumps(meta)}, files={"file": ("t.wav", wav_bytes(raw), "audio/wav")},
                        headers={"X-User": uid}).json()
        takes.append(t["id"])
    for tid, uid in zip(takes, ids):
        wait_job(client, h, lambda tid=tid, uid=uid: client.get(f"/api/takes/{tid}").json()["status"] == "ready", timeout=180)
    return ids, takes, p


def test_labels_and_exports(client):
    ids, takes, phrase = _setup(client)
    h = {"X-User": ids[0]}
    # labels: register + one quality + rhythm; a second take with two qualities; vocab is Korean
    v = client.get("/api/labels/vocab").json()
    assert [o["label"] for o in v["register"]] == ["흉성", "믹스", "가성"]
    r = client.put(f"/api/takes/{takes[0]}/labels", json={"register": "chest", "qualities": ["breathy"], "rhythm": "ok", "memo": "좋음"}, headers=h)
    assert r.json()["labels"]["qualities"] == ["breathy"]
    client.put(f"/api/takes/{takes[1]}/labels", json={"register": "falsetto", "qualities": ["breathy", "pharyngeal_twang"], "rhythm": "off"}, headers=h)
    client.put(f"/api/takes/{takes[2]}/labels", json={"register": "mixed", "qualities": ["none", "fry"]}, headers=h)
    assert client.get(f"/api/takes/{takes[2]}/labels").json()["labels"]["qualities"] == ["none"]  # "해당 없음" excludes the rest
    q = client.get("/api/data/takes?who=all&unlabeled=true", headers=h).json()["takes"]
    assert q == []

    layout = client.app.state.studio.layout
    # evaluation export → gyeol eval realset reads it
    job = client.post("/api/exports", json={"kind": "eval", "scope": "all"}, headers=h).json()["job"]
    done = wait_job(client, h, lambda: (j := client.get(f"/api/jobs/{job['id']}").json())["status"] in ("done", "failed") and j)
    assert done["status"] == "done", done
    d = Path(done["result"]["dir"])
    from gyeol.eval.realset import load_realset

    rs = load_realset(d)
    assert rs.ok, rs.reason
    users = rs.value.users
    assert {u.singer for u in users} == {ids[0], ids[1]}  # 가수3 did not consent to training
    first = next(u for u in users if u.singer == ids[0])
    assert first.annotations == {"rhythm_ok": True} and first.recording["route"] == "wired" and first.condition == "clean"
    assert "가수1" not in (d / "manifest.jsonl").read_text(encoding="utf-8")  # pseudonymous ids only

    # commercial scope: only 가수1
    job = client.post("/api/exports", json={"kind": "eval", "scope": "commercial"}, headers=h).json()["job"]
    done = wait_job(client, h, lambda: (j := client.get(f"/api/jobs/{job['id']}").json())["status"] in ("done", "failed") and j)
    assert done["result"]["users"] == [ids[0]]

    # training export → recordings.json (scan_own) and manifest.json (open_manifest)
    job = client.post("/api/exports", json={"kind": "train", "scope": "all"}, headers=h).json()["job"]
    done = wait_job(client, h, lambda: (j := client.get(f"/api/jobs/{job['id']}").json())["status"] in ("done", "failed") and j)
    assert done["status"] == "done", done
    d = Path(done["result"]["dir"])
    from gyeol.data.adapters import scan_own
    from gyeol.data.manifest import open_manifest

    sc = scan_own(d)
    assert sc.ok and len(sc.value.manifest.items) == 2
    labels = {i.singer: i.labels for i in sc.value.manifest.items}
    assert labels[ids[0]] == {"register": "chest", "phonation": "breathy", "rhythm_ok": True}
    assert labels[ids[1]] == {"register": "falsetto", "qualities": ["breathy", "pharyngeal_twang"], "rhythm_ok": False}
    ds = open_manifest(d / "manifest.json")
    assert len(ds) == 2 and all(ds.resolve(i).is_file() for i in ds)
    assert ds.info["name"] == "own_recordings"

    # listing, and deleting a person removes the export folders that hold their voice
    ex = client.get("/api/exports", headers=h).json()
    assert len(ex["exports"]) == 3 and ex["eligible"]["all"]["train"] == 2
    client.request("DELETE", f"/api/users/{ids[1]}", json={"confirm_name": "가수2"})
    left = client.get("/api/exports", headers=h).json()["exports"]
    assert [e["users"] for e in left] == [[ids[0]]]
    assert len(list((layout.exports).iterdir())) == 1


def test_feedback_responses_summary(client):
    ids, takes, _ = _setup(client, users=(("응답자", True, False),), detune=-50.0)
    h = {"X-User": ids[0]}
    fb = client.post(f"/api/takes/{takes[0]}/self-assessment", json={"noticed": ["nothing"]}, headers=h).json()
    co = fb["coaching"]
    assert co["primary"] is not None, co
    key = co["primary"]["key"]
    assert client.post(f"/api/feedback/{fb['feedback_id']}/responses", json={"item_key": key, "response": "maybe"}, headers=h).status_code == 400
    client.post(f"/api/feedback/{fb['feedback_id']}/responses", json={"item_key": key, "response": "disagree"}, headers=h)
    client.post(f"/api/feedback/{fb['feedback_id']}/responses", json={"item_key": key, "response": "agree"}, headers=h)  # changing an answer
    s = client.get("/api/data/summary", headers=h).json()
    cat, attr, _ = key.split(":")
    assert s["responses"] == 1 and s["responses_by_item"][f"{cat}:{attr}"]["agree"] == 1
