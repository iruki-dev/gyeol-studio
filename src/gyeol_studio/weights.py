"""Model weights the app needs, fetched with ``gyeol fetch`` into gyeol's cache folder.

Only the vocal-separation model (BS-RoFormer, ~640 MB) is downloaded; pitch
analysis uses gyeol's built-in DSP trackers and needs no weights.
"""

from __future__ import annotations

import os
from pathlib import Path

SEPARATION = "bs_roformer_viperx_ep317"
REQUIRED = (SEPARATION,)
LABEL = {SEPARATION: "보컬 분리 모델 (BS-RoFormer)"}
EXPECTED_SIZE = {SEPARATION: 639_331_213}  # from gyeol's asset notes; used for progress when the server sends no size


def cache_dir() -> Path:
    from gyeol.cli import CACHE

    return Path(CACHE)


# gyeol's asset list is in English; testers read these in Korean (the original stays alongside for reference)
KO = {
    SEPARATION: {"license_ko": "원 제작자가 라이선스를 밝히지 않음 (공개 RoFormer 모델 모음에는 MIT로 올라 있음)",
                 "source_ko": "viperx가 공개한 BS-RoFormer 보컬 분리 모델 (UVR 공개 모델 저장소). 학습에 쓴 데이터는 공개되지 않았어요."},
    "own_recordings": {"license_ko": "이 앱으로 직접 녹음한 데이터", "source_ko": "테스터가 동의하고 녹음한 소리"},
}


def describe(name: str) -> dict:
    """gyeol's description of a weights file or dataset, with Korean wording when the app has it."""
    from gyeol.core.assets import describe as _describe

    d = dict(_describe(name))
    d.update(KO.get(name, {}))
    d.setdefault("license_ko", d.get("license"))
    d.setdefault("source_ko", d.get("source"))
    return d


def asset_info(name: str) -> dict:
    from gyeol.core.assets import asset

    a = asset(name)
    return {"name": a.name, "license": a.license, "source": a.source, "url": a.url, "sha256": a.sha256, "notes": list(a.notes),
            **KO.get(name, {})}


def target_path(name: str) -> Path | None:
    info = asset_info(name)
    if not info["url"]:
        return None
    return cache_dir() / name / Path(info["url"]).name


def part_path(name: str) -> Path | None:
    p = target_path(name)
    return None if p is None else p.with_name(p.name + ".part")


def status(name: str) -> dict:
    p = target_path(name)
    present = bool(p and p.exists() and p.stat().st_size > 0 and not (EXPECTED_SIZE.get(name) and p.stat().st_size != EXPECTED_SIZE[name]))
    part = part_path(name)
    out = {"name": name, "label": LABEL.get(name, name), "present": present, "path": str(p) if p else None,
           "size": p.stat().st_size if present else 0, "expected_size": EXPECTED_SIZE.get(name)}
    if part is not None and part.exists():
        out["partial_size"] = part.stat().st_size
    info = asset_info(name)
    out.update(license=info.get("license_ko", info["license"]), source=info.get("source_ko", info["source"]),
               license_original=info["license"])
    return out


def all_present() -> bool:
    return all(status(n)["present"] for n in REQUIRED)


def remote_size(url: str, timeout: float = 15.0) -> int | None:
    import urllib.request

    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https URL from gyeol's asset list
            n = r.headers.get("Content-Length")
            return int(n) if n else None
    except Exception:  # noqa: BLE001 - size is only for the progress bar
        return None


def free_bytes(path: Path) -> int:
    import shutil

    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def remove_partial(name: str) -> None:
    part = part_path(name)
    if part is not None and part.exists():
        os.unlink(part)
