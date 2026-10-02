"""Phone connection: the https address as a QR code, and the local CA certificate download."""

from __future__ import annotations

import io
import time

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ..deps import state

router = APIRouter()


def qr_svg(text: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


@router.get("/api/network")
def network(request: Request):
    st = state(request)
    h = st.https_info or {}
    urls = [f"https://{a}:{h['port']}/" for a in h.get("addresses", [])] if h.get("port") else []
    out = {"enabled": bool(urls), "urls": urls, "http_port": h.get("http_port"), "https_port": h.get("port")}
    if urls:
        from ..certs import ca_fingerprint

        out["qr"] = [{"url": u, "svg": qr_svg(u)} for u in urls]
        out["ca_urls"] = [f"http://{a}:{h['http_port']}/ca.crt" for a in h.get("addresses", [])]
        out["ca_qrs"] = [qr_svg(u) for u in out["ca_urls"]]
        out["ca_fingerprint"] = ca_fingerprint()
    now = time.time()
    out["devices"] = [{"ago_s": round(now - d["seen"]), "kind": device_kind(d["agent"])}
                      for _, d in sorted(st.devices.items(), key=lambda kv: -kv[1]["seen"]) if now - d["seen"] < 3600][:5]
    return out


def device_kind(agent: str) -> str:
    """A short Korean name for the device from its browser's user-agent ("아이폰 · 사파리")."""
    a = agent.lower()
    dev = "아이폰" if "iphone" in a else "아이패드" if "ipad" in a else "안드로이드 휴대폰" if "android" in a else \
        "맥" if "macintosh" in a else "윈도우 PC" if "windows" in a else "리눅스 PC" if "linux" in a else "기기"
    br = "삼성 인터넷" if "samsungbrowser" in a else "크롬" if ("chrome" in a or "crios" in a) else "파이어폭스" if "firefox" in a else \
        "사파리" if "safari" in a else "브라우저"
    return f"{dev} · {br}"


@router.get("/ca.crt", include_in_schema=False)
def ca_certificate():
    from ..certs import ca_pem

    return Response(ca_pem(), media_type="application/x-x509-ca-cert",
                    headers={"Content-Disposition": 'attachment; filename="gyeol-studio-ca.crt"'})
