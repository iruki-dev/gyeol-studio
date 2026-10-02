"""Phone connection: the https address as a QR code, and the local CA certificate download."""

from __future__ import annotations

import io

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
        out["ca_qr"] = qr_svg(out["ca_urls"][0])
        out["ca_fingerprint"] = ca_fingerprint()
    return out


@router.get("/ca.crt", include_in_schema=False)
def ca_certificate():
    from ..certs import ca_pem

    return Response(ca_pem(), media_type="application/x-x509-ca-cert",
                    headers={"Content-Disposition": 'attachment; filename="gyeol-studio-ca.crt"'})
