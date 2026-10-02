"""The phase-1 flow through the HTTP API with real worker processes: song → phrase → take → feedback → demo."""

from __future__ import annotations

import json

import numpy as np

from .conftest import SR, melody_audio, wait_job, wav_bytes


def _user(client, name="테스터", training=True):
    r = client.post("/api/users", json={"name": name, "consent": {"analysis": True, "training": training, "commercial": False,
                                                                     "retention_days": 365}})
    assert r.status_code == 200, r.text
    return r.json()


def test_consent_required(client):
    r = client.post("/api/users", json={"name": "a", "consent": {"analysis": False}})
    assert r.status_code == 400
    assert "동의" in r.json()["error"]["message"]


def test_full_flow(client):
    u = _user(client)
    h = {"X-User": u["id"]}
    target = np.r_[np.zeros(int(0.5 * SR)), melody_audio(), np.zeros(int(0.5 * SR))]
    r = client.post("/api/songs", data={"title": "연습곡", "artist": "합성", "song_key": "C", "vocal_only": "true"},
                    files={"file": ("guide.wav", wav_bytes(target), "audio/wav")}, headers=h)
    assert r.status_code == 200, r.text
    song = r.json()
    wait_job(client, h, lambda: client.get(f"/api/songs/{song['id']}").json()["status"] == "ready")
    dur = len(target) / SR
    r = client.post(f"/api/songs/{song['id']}/phrases", json={"start_s": 0.3, "end_s": dur - 0.2, "lyrics": "사랑 해요 그대"}, headers=h)
    assert r.status_code == 200, r.text
    ph = r.json()
    ph = wait_job(client, h, lambda: (p := client.get(f"/api/phrases/{ph['id']}").json())["status"] == "ready" and p)
    assert ph["target"]["syllables"], "lyrics should map onto notes"
    # a take: flat on the third note and late on the fourth, recorded with 2 s of lead-in and 120 ms latency
    take = np.r_[np.zeros(int(0.5 * SR)), melody_audio(detune=(0, 0, -45, 0, 0, 0), shifts=(0, 0, 0, 0.09, 0, 0), seed=3), np.zeros(int(0.5 * SR))]
    seg = take[int(0.3 * SR):int((dur - 0.2) * SR)]
    raw = np.r_[np.zeros(int((2.0 + 0.12) * SR)), seg, np.zeros(int(1.0 * SR))]
    meta = {"phrase_offset_s": 2.12, "latency_ms": 120, "latency_method": "loopback",
            "conditions": {"device": "노트북", "earphone": "wired", "backing": "on", "place": "집"}}
    r = client.post(f"/api/phrases/{ph['id']}/takes", data={"meta": json.dumps(meta)}, files={"file": ("take.wav", wav_bytes(raw), "audio/wav")},
                    headers=h)
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["consent_training"] == 1 and t["conditions"]["earphone"] == "wired"
    fb = wait_job(client, h, lambda: (f := client.get(f"/api/takes/{t['id']}/feedback", headers=h).json()).get("feedback_id") and f, timeout=180)
    assert fb["revealed"] is False and fb["options"]
    r = client.post(f"/api/takes/{t['id']}/self-assessment", json={"noticed": ["pitch"]}, headers=h)
    assert r.status_code == 200, r.text
    fb = r.json()
    co = fb["coaching"]
    assert co["primary"] is not None, co
    assert co["primary"]["category"] in ("pitch", "rhythm")
    assert len(co["secondary"]) <= 2
    assert fb["self_assessment"]["match"] in ("matched", "missed")
    ev = fb["evidence"]
    assert len(ev["times"]) == len(ev["user_cents"]) == len(ev["target_cents"])
    assert ev["syllables"]
    key = co["primary"]["key"]
    r = client.post(f"/api/feedback/{fb['feedback_id']}/responses", json={"item_key": key, "response": "agree"}, headers=h)
    assert r.status_code == 200
    demos = wait_job(client, h, lambda: (d := client.get(f"/api/takes/{t['id']}/feedback", headers=h).json()["demos"]).get(key, {}).get("status")
                     in ("ready", "failed") and d)
    assert demos[key]["status"] == "ready", demos
    f = demos[key]["files"]["step_1"]
    assert client.get(f"/api/files/{f}").status_code == 200
    assert client.get("/api/files/../studio.db").status_code == 404
    # stored analyses carry their schema tags
    conn = client.app.state.studio.conn()
    kinds = {r["kind"]: (r["schema"], r["version"]) for r in conn.execute("SELECT kind, schema, version FROM analyses").fetchall()}
    assert kinds["target"][0] == "gyeol.representation" and kinds["explanation"][0] == "gyeol.explanation"


def test_delete_user_removes_everything(client):
    u = _user(client, "지울사람")
    h = {"X-User": u["id"]}
    r = client.request("DELETE", f"/api/users/{u['id']}", json={"confirm_name": "틀림"}, headers=h)
    assert r.status_code == 400
    r = client.request("DELETE", f"/api/users/{u['id']}", json={"confirm_name": "지울사람"}, headers=h)
    assert r.json()["deleted"]
    conn = client.app.state.studio.conn()
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM consents").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM deletion_log").fetchone()[0] == 1
