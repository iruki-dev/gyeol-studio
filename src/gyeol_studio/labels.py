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


# Technique recording mode: the app asks for the same phrase twice — once without and once with a technique — and
# stores the pair (``pair_id``, ``pair_role`` off/on, as gyeol's paired loader expects) with the labels already set.
TECHNIQUES = {
    "register": {"label": "흉성 ↔ 가성", "off": ("흉성", "말할 때처럼 가슴이 울리는 단단한 소리로", {"register": "chest"}),
                 "on": ("가성", "가볍고 바람이 조금 섞인 머리 울림 소리로", {"register": "falsetto"})},
    "mixed": {"label": "흉성 ↔ 믹스", "off": ("흉성", "말할 때처럼 가슴이 울리는 단단한 소리로", {"register": "chest"}),
              "on": ("믹스", "흉성과 가성의 중간, 높은 음도 편하게 이어지는 소리로", {"register": "mixed"})},
    "breathy": {"label": "맑은 소리 ↔ 숨섞인 소리", "off": ("맑은 소리", "숨이 새지 않게 또렷하게", {"qualities": ["none"]}),
                "on": ("숨섞인 소리", "속삭이듯 숨을 많이 섞어서", {"qualities": ["breathy"]})},
    "pressed_belt": {"label": "편한 소리 ↔ 압착·벨팅", "off": ("편한 소리", "힘을 빼고 편하게", {"qualities": ["none"]}),
                     "on": ("압착·벨팅", "힘주어 세게 밀어내듯 (목이 아프면 바로 멈추세요)", {"qualities": ["pressed_belt"]})},
    "pharyngeal_twang": {"label": "보통 ↔ 트왱", "off": ("보통 소리", "평소처럼", {"qualities": ["none"]}),
                         "on": ("트왱", "코와 입천장 쪽으로 쨍하게 모아서", {"qualities": ["pharyngeal_twang"]})},
    "fry": {"label": "보통 ↔ 프라이", "off": ("보통 소리", "평소처럼", {"qualities": ["none"]}),
            "on": ("프라이", "지글지글 끓는 듯한 낮은 소리로 (무리하지 마세요)", {"qualities": ["fry"]})},
}


def techniques() -> list[dict]:
    return [{"id": k, "label": v["label"], "steps": [{"role": r, "label": v[r][0], "how": v[r][1]} for r in ("off", "on")]}
            for k, v in TECHNIQUES.items()]


def technique_labels(contrast: str, role: str) -> dict | None:
    t = TECHNIQUES.get(contrast)
    if t is None or role not in ("off", "on"):
        return None
    return {"register": None, "qualities": None, "rhythm": None, "memo": "", **t[role][2]}
