"""Phase 3: start check scoring (gyeol.coach.onboarding), phrase range check, history, profiles."""

from __future__ import annotations

import json

import numpy as np

from .conftest import SR, wait_job, wav_bytes


def _sing(cents: list[float], dur: float = 0.5, seed: int = 0) -> np.ndarray:
    from gyeol import api

    notes = [api.SynthNote(440.0 * 2 ** (c / 1200), dur, gap_after=0.06, vowel="a") for c in cents]
    return np.r_[np.zeros(SR // 5), api.melody(notes, sr=SR, seed=seed).audio, np.zeros(SR // 5)]


def _post(client, cid, h, task, x, targets=()):
    r = client.post(f"/api/checks/{cid}/recordings", data={"meta": json.dumps({"task": task, "targets": list(targets)})},
                    files={"file": ("t.wav", wav_bytes(x), "audio/wav")}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_start_check(client):
    u = client.post("/api/users", json={"name": "검사", "consent": {"analysis": True}}).json()
    h = {"X-User": u["id"]}
    cid = client.post("/api/checks", headers=h).json()["id"]
    # range: glides over C3…C5 in small steps, comfortable notes around A3–E4
    _post(client, cid, h, "glide", _sing(list(np.arange(-2100, 301, 100)), dur=0.12))
    _post(client, cid, h, "glide", _sing(list(np.arange(300, -2101, -100)), dur=0.12, seed=1))
    r = _post(client, cid, h, "comfortable", _sing([-1200, -1000, -800, -700, -500, -700, -800, -1000, -1200], dur=0.35))
    assert r["median_cents"] is not None and -1250 < r["median_cents"] < -450
    c0 = -900.0
    # singing back: 30 cents sharp on average, consistent
    for k, t in enumerate([c0, c0 + 400, c0 - 300, c0, c0 + 400, c0 - 300]):
        _post(client, cid, h, "match", _sing([t + 30 + (k % 2) * 10], dur=1.2, seed=k), [t])
    for a, b in ([c0, c0 + 400], [c0 + 200, c0 - 100], [c0 - 300, c0 + 400]):
        _post(client, cid, h, "interval", _sing([a, b], dur=0.8), [a, b])
    mel = [c0 - 200, c0, c0 + 200, c0, c0 - 200]
    _post(client, cid, h, "melody", _sing(mel, dur=0.5), mel)
    # hearing: always right at 100/50 cents, chance below
    disc = [{"delta": d, "correct": d >= 50 or i % 2 == 0} for d in (100, 50, 25, 12) for i in range(4)]
    r = client.post(f"/api/checks/{cid}/finish", json={"discrimination": disc}, headers=h).json()
    c = wait_job(client, h, lambda: (x := client.get(f"/api/checks/{cid}").json())["status"] == "done" and x, timeout=240)
    p = c["profile"]
    assert p["production_band"] == "on_target" and p["production_mae_cents"] < 60
    assert p["precision_band"] == "consistent"
    assert p["perception_band"] in ("fine", "developing") and p["status"]["perception"] in ("ok", "not_reached")
    vr = p["voice_range"]
    assert vr and vr["low_cents"] < vr["tess_low_cents"] < vr["tess_high_cents"] < vr["high_cents"]
    titles = [s["title"] for s in c["summary"]]
    assert titles[:4] == ["음역", "음 따라 부르기", "같은 음 다시 부르기", "음 구별 듣기"]
    assert "음치" not in json.dumps(c["summary"], ensure_ascii=False)
    me = client.get(f"/api/users/{u['id']}").json()
    assert me["voice_range"]["tess_high_cents"] == vr["tess_high_cents"] and me["onboarding"]["check_id"] == cid
    stored = client.app.state.studio.conn().execute("SELECT COUNT(*) FROM analyses WHERE owner_id=? AND schema='gyeol.representation'", (cid,)).fetchone()[0]
    assert stored == 13  # every check recording's analysis is kept as gyeol JSON

    # a phrase far above the comfortable range gets a key suggestion
    song = client.post("/api/songs", data={"title": "높은 곡", "vocal_only": "true"}, files={"file": ("g.wav", wav_bytes(_sing([600, 700, 900, 700, 600], dur=0.6)), "audio/wav")},
                       headers=h).json()
    wait_job(client, h, lambda: client.get(f"/api/songs/{song['id']}").json()["status"] == "ready")
    ph = client.post(f"/api/songs/{song['id']}/phrases", json={"start_s": 0.1, "end_s": 3.4}).json()
    wait_job(client, h, lambda: client.get(f"/api/phrases/{ph['id']}").json()["status"] == "ready")
    rc = client.get(f"/api/phrases/{ph['id']}/range-check", headers=h).json()
    assert rc["available"] and (rc["status"] != "comfortable" or rc["octave_shift_cents"] != 0), rc
    assert rc["texts"]


def test_history_and_wellbeing(client):
    u = client.post("/api/users", json={"name": "기록", "consent": {"analysis": True}}).json()
    h = {"X-User": u["id"]}
    tgt = _sing([-900, -700, -500, -700, -900], dur=0.6)
    song = client.post("/api/songs", data={"title": "곡", "vocal_only": "true"}, files={"file": ("g.wav", wav_bytes(tgt), "audio/wav")}, headers=h).json()
    wait_job(client, h, lambda: client.get(f"/api/songs/{song['id']}").json()["status"] == "ready")
    dur = len(tgt) / SR
    ph = client.post(f"/api/songs/{song['id']}/phrases", json={"start_s": 0.1, "end_s": dur - 0.1}).json()
    wait_job(client, h, lambda: client.get(f"/api/phrases/{ph['id']}").json()["status"] == "ready")
    for k, det in enumerate((-60, -30)):  # getting closer
        take = _sing([-900, -700 + det, -500, -700, -900], dur=0.6, seed=k + 3)[int(0.1 * SR):int((dur - 0.1) * SR)]
        raw = np.r_[np.zeros(SR), take, np.zeros(SR // 2)]
        t = client.post(f"/api/phrases/{ph['id']}/takes", data={"meta": json.dumps({"phrase_offset_s": 1.0})},
                        files={"file": ("t.wav", wav_bytes(raw), "audio/wav")}, headers=h).json()
        wait_job(client, h, lambda t=t: client.get(f"/api/takes/{t['id']}").json()["status"] == "ready", timeout=180)
    hist = client.get(f"/api/history/phrase/{ph['id']}", headers=h).json()
    assert len(hist["points"]) == 2 and set(hist["tracks"]) == {"pitch", "rhythm", "dynamics"}
    assert client.get("/api/history/phrases", headers=h).json()["phrases"][0]["n"] == 2
    wb = client.get("/api/history/wellbeing", headers=h).json()
    assert len(wb["days"]) == 14 and wb["today_s"] > 2.0 and wb["session_s"] == wb["today_s"]
    assert wb["norms"]["daily_warn_s"] == 1800.0 and wb["fatigue"] == []


def test_profiles_switch_and_rename(client):
    a = client.post("/api/users", json={"name": "가", "consent": {"analysis": True}}).json()
    b = client.post("/api/users", json={"name": "나", "consent": {"analysis": True, "training": True}}).json()
    assert [u["name"] for u in client.get("/api/users").json()["users"]] == ["가", "나"]
    assert client.patch(f"/api/users/{a['id']}", json={"name": "나"}).status_code == 409
    r = client.patch(f"/api/users/{b['id']}", json={"consent": {"analysis": True, "training": False, "commercial": True}}).json()
    assert r["consent_training"] is False and r["consent_commercial"] is False  # commercial needs training
    assert len(client.get(f"/api/users/{b['id']}/consents").json()["history"]) == 2
