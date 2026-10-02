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


def asset_info(name: str) -> dict:
    from gyeol.core.assets import asset

    a = asset(name)
    return {"name": a.name, "license": a.license, "source": a.source, "url": a.url, "sha256": a.sha256, "notes": list(a.notes)}


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
    out.update(license=info["license"], source=info["source"])
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
