"""Phase 4: technique pairs (auto-labelled), training with gyeol.api.train through the train worker, stop/resume, apply/rollback."""

from __future__ import annotations

import json
import time
import uuid

import numpy as np

from .conftest import SR, wait_job, wav_bytes


def _sing(cents, seed, breathy=False):
    from gyeol import api

    notes = [api.SynthNote(440.0 * 2 ** (c / 1200), 0.5, gap_after=0.05, vowel="a") for c in cents]
    x = api.melody(notes, sr=SR, seed=seed).audio
    if breathy:  # a crude breathy voice: more noise, less harmonic level
        x = 0.6 * x + 0.05 * np.random.default_rng(seed).standard_normal(len(x))
    return x


def test_technique_pairs_and_training(client):
    phrase_notes = [-900, -700, -500, -700, -900]
    owner = client.post("/api/users", json={"name": "곡주인", "consent": {"analysis": True}}).json()
    tgt = np.r_[np.zeros(SR // 5), _sing(phrase_notes, 0), np.zeros(SR // 5)]
    song = client.post("/api/songs", data={"title": "연습곡", "vocal_only": "true"}, files={"file": ("g.wav", wav_bytes(tgt), "audio/wav")},
                       headers={"X-User": owner["id"]}).json()
    wait_job(client, {}, lambda: client.get(f"/api/songs/{song['id']}").json()["status"] == "ready")
    dur = len(tgt) / SR
    ph = client.post(f"/api/songs/{song['id']}/phrases", json={"start_s": 0.1, "end_s": dur - 0.1}).json()
    wait_job(client, {}, lambda: client.get(f"/api/phrases/{ph['id']}").json()["status"] == "ready")
    cat = {t["id"]: t for t in client.get("/api/techniques").json()["techniques"]}
    assert cat["breathy"]["steps"][1]["label"] == "숨섞인 소리"

    singers = []
    for i in range(4):
        u = client.post("/api/users", json={"name": f"가수{i}", "consent": {"analysis": True, "training": True, "commercial": i < 2}}).json()
        singers.append(u)
        for rep in range(2):
            pair = uuid.uuid4().hex[:12]
            for role in ("off", "on"):
                x = _sing([c + 100 * i for c in phrase_notes], seed=10 * i + rep, breathy=role == "on")[int(0.1 * SR):int((dur - 0.1) * SR)]
                raw = np.r_[np.zeros(SR), x, np.zeros(SR // 2)]
                meta = {"phrase_offset_s": 1.0, "kind": "technique", "pair_id": pair, "pair_role": role,
                        "technique": {"contrast": "breathy", "label": cat["breathy"]["label"]}}
                r = client.post(f"/api/phrases/{ph['id']}/takes", data={"meta": json.dumps(meta)}, files={"file": ("t.wav", wav_bytes(raw), "audio/wav")},
                                headers={"X-User": u["id"]})
                assert r.status_code == 200, r.text
                assert r.json()["labels"]["qualities"] == (["breathy"] if role == "on" else ["none"])

    ov = client.get("/api/training").json()
    assert ov["eligible"]["all"] == {"takes": 16, "users": 4, "pairs": 8}
    assert ov["eligible"]["commercial"]["users"] == 2
    h = {"X-User": singers[0]["id"]}
    r = client.post("/api/training/runs", json={"scope": "commercial", "preset": "quick"}, headers=h)
    assert r.status_code == 400 and "3명" in r.json()["error"]["message"]

    run = client.post("/api/training/runs", json={"scope": "all", "preset": "quick"}, headers=h).json()
    rid = run["id"]
    # stop once training has started, then resume from the saved state
    wait_job(client, h, lambda: ((client.get("/api/training").json()["runs"][0]["progress"] or {}).get("step") or 0) >= 10, timeout=300, every=0.3)
    client.post(f"/api/training/runs/{rid}/stop", headers=h)
    paused = wait_job(client, h, lambda: (x := client.get("/api/training").json()["runs"][0])["status"] == "paused" and x, timeout=120)
    step_at_pause = paused["progress"]["step"]
    assert paused["job"]["status"] == "paused" and 10 <= step_at_pause < 200
    client.post(f"/api/training/runs/{rid}/resume", headers=h)
    done = wait_job(client, h, lambda: (x := client.get("/api/training").json()["runs"][0])["status"] in ("done", "failed") and x, timeout=600)
    assert done["status"] == "done", (done["job"] or {}).get("error_detail")
    assert done["has_checkpoint"] and done["metrics"], done
    assert done["data_summary"]["pairs"] == 8 and done["data_summary"]["label_counts"]["phonation:breathy"] == 8
    assert done["provenance"]["sources"] == ["own_recordings"]
    assert done["provenance"]["sources_info"][0]["license"] == "your own recordings"
    assert done["progress"]["history"] and any(hh["step"] > step_at_pause for hh in done["progress"]["history"])

    # apply, then roll back to the built-in analysis
    ov = client.post(f"/api/training/runs/{rid}/apply", headers=h).json()
    assert ov["active"] == rid
    ov = client.post("/api/training/rollback", headers=h).json()
    assert ov["active"] is None
    # deleting a singer removes the run's copy of their recordings and the prepared features
    layout = client.app.state.studio.layout
    d = layout.training / "runs" / rid
    assert (d / "data").exists() and (d / "cache").exists()
    client.request("DELETE", f"/api/users/{singers[3]['id']}", json={"confirm_name": "가수3"})
    assert not (d / "data").exists() and not (d / "cache").exists() and (d / "out" / "best.pt").exists()
    time.sleep(0.1)
