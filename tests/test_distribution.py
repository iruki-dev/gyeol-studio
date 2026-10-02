"""Phase 5: phone connection (https addresses, QR codes, certificate, connected devices) and Korean wording."""

from __future__ import annotations

import re

import pytest


@pytest.fixture()
def lan_client(env):
    from fastapi.testclient import TestClient

    from gyeol_studio.server import create_app

    info = {"port": 8766, "http_port": 8765, "addresses": ["192.168.0.10", "10.0.0.5"]}
    app = create_app(env, https_info=info)
    with TestClient(app, base_url="https://192.168.0.10:8766", client=("192.168.0.23", 50000)) as c:
        yield c


IPHONE = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17.0 Mobile Safari/604.1"}


def test_network_addresses_and_devices(lan_client):
    n = lan_client.get("/api/network", headers=IPHONE).json()
    assert n["urls"] == ["https://192.168.0.10:8766/", "https://10.0.0.5:8766/"]
    assert len(n["qr"]) == 2 and len(n["ca_qrs"]) == 2 and n["ca_urls"][1] == "http://10.0.0.5:8765/ca.crt"
    assert all(q["svg"].lstrip().startswith("<?xml") or "<svg" in q["svg"] for q in n["qr"])
    # the phone that asked is listed, so the PC screen can say "connected"
    n = lan_client.get("/api/network", headers=IPHONE).json()
    assert n["devices"] and n["devices"][0]["kind"] == "아이폰 · 사파리" and n["devices"][0]["ago_s"] <= 2


def test_plain_http_from_phone_goes_to_https_except_certificate(env):
    from fastapi.testclient import TestClient

    from gyeol_studio.server import create_app

    app = create_app(env, https_info={"port": 8766, "http_port": 8765, "addresses": ["192.168.0.10"]})
    with TestClient(app, base_url="http://192.168.0.10:8765", client=("192.168.0.23", 50000)) as c:
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == "https://192.168.0.10:8766/"
        r = c.get("/ca.crt", follow_redirects=False)
        assert r.status_code == 200 and b"BEGIN CERTIFICATE" in r.content


def test_device_kind():
    from gyeol_studio.routes.network import device_kind

    assert device_kind("Mozilla/5.0 (Linux; Android 14; SM-S911N) SamsungBrowser/24.0 Chrome/117.0 Mobile Safari/537.36") == "안드로이드 휴대폰 · 삼성 인터넷"
    assert device_kind("Mozilla/5.0 (Linux; Android 14) Chrome/120.0 Mobile Safari/537.36") == "안드로이드 휴대폰 · 크롬"
    assert device_kind("") == "기기 · 브라우저"


def test_weights_and_provenance_described_in_korean(client):
    st = client.get("/api/status").json()
    w = st["weights"][0]
    assert re.search("[가-힣]", w["license"]) and re.search("[가-힣]", w["source"]) and w["license_original"]
    from gyeol_studio.weights import describe

    d = describe("own_recordings")
    assert d["license"] == "your own recordings" and re.search("[가-힣]", d["license_ko"])


def test_error_messages_are_korean(client):
    # a few user-facing errors: what went wrong + what to do, in Korean
    for r in (client.post("/api/users", json={"name": "", "consent": {"analysis": True}}),
              client.post("/api/users", json={"name": "가", "consent": {"analysis": False}}),
              client.get("/api/songs/nope"),
              client.post("/api/training/runs", json={"scope": "all"}, headers={"X-User": "nobody"})):
        msg = r.json()["error"]["message"]
        assert r.status_code >= 400 and re.search("[가-힣]", msg) and not re.search("[A-Za-z]{4,}", msg), msg
