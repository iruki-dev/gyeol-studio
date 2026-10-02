"""Label vocabulary (Korean on screen, gyeol's vocabulary in exports).

gyeol's heads learn ``register`` (chest / mixed / falsetto) and one phonation
quality per recording (``breathy``, ``pressed_belt``, ``pharyngeal_twang``,
``fry``, ``rough``; ``gyeol.attributes.heads``).  The app lets people tick
several qualities; an export carries ``phonation`` only when exactly one (or
"none") is ticked — see docs/library-requests.md.
"""

from __future__ import annotations

REGISTER = {
    "chest": ("흉성", "말할 때처럼 가슴이 울리는 단단한 소리"),
    "mixed": ("믹스", "흉성과 가성을 섞은 중간 소리"),
    "falsetto": ("가성", "가볍고 바람이 조금 섞인 높은 소리"),
}
QUALITIES = {
    "breathy": ("숨섞임", "소리에 바람(숨) 소리가 섞여요"),
    "pressed_belt": ("압착·벨팅", "목에 힘을 주어 세게 밀어내는 소리"),
    "pharyngeal_twang": ("트왱", "코와 입천장 쪽으로 쨍하게 모이는 밝은 소리"),
    "fry": ("프라이", "지글지글 끓는 듯한 낮은 소리"),
    "rough": ("거침", "갈라지거나 쉰 듯한 소리"),
}
NO_QUALITY = "none"
RHYTHM = {"ok": ("맞음", "박자가 반주와 맞았어요"), "off": ("틀림", "빠르거나 늦게 들어간 곳이 있어요")}


def vocab() -> dict:
    return {
        "register": [{"id": k, "label": v[0], "help": v[1]} for k, v in REGISTER.items()],
        "qualities": [{"id": k, "label": v[0], "help": v[1]} for k, v in QUALITIES.items()]
        + [{"id": NO_QUALITY, "label": "해당 없음", "help": "위의 특징이 없는 맑은 소리"}],
        "rhythm": [{"id": k, "label": v[0], "help": v[1]} for k, v in RHYTHM.items()],
    }


def clean(body: dict) -> dict:
    reg = body.get("register")
    reg = reg if reg in REGISTER else None
    q = body.get("qualities")
    if q is None:
        qs = None
    else:
        qs = sorted({x for x in q if x in QUALITIES or x == NO_QUALITY})
        if NO_QUALITY in qs:
            qs = [NO_QUALITY]
    rh = body.get("rhythm")
    rh = rh if rh in RHYTHM else None
    memo = str(body.get("memo") or "")[:500]
    return {"register": reg, "qualities": qs, "rhythm": rh, "memo": memo}


def to_gyeol(lab: dict | None) -> dict:
    """App labels → gyeol's training vocabulary (``register``, ``phonation``) plus the app's extras."""
    out: dict = {}
    if not lab:
        return out
    if lab.get("register"):
        out["register"] = lab["register"]
    qs = lab.get("qualities")
    if qs is not None:
        if qs == [NO_QUALITY]:
            out["phonation"] = None  # labelled: none of the qualities (negatives for every labelled quality)
        elif len(qs) == 1:
            out["phonation"] = qs[0]
        elif qs:
            out["qualities"] = qs  # several at once: gyeol takes one phonation label per recording
    if lab.get("rhythm"):
        out["rhythm_ok"] = lab["rhythm"] == "ok"
    return out
