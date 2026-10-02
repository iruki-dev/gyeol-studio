"""App settings and the data-folder layout.

Settings live in a small JSON file in the platform's config folder (outside the
data folder, because the data folder's location is itself a setting):

* Windows: ``%APPDATA%\\gyeol-studio\\settings.json``
* macOS: ``~/Library/Application Support/gyeol-studio/settings.json``
* Linux: ``$XDG_CONFIG_HOME/gyeol-studio/settings.json``

``GYEOL_STUDIO_CONFIG`` overrides the config folder (tests, portable installs).
Everything the app stores about people and songs goes in the one data folder.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP = "gyeol-studio"


def config_dir() -> Path:
    env = os.environ.get("GYEOL_STUDIO_CONFIG")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP


def default_data_dir() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "gyeol-studio"


@dataclass
class Advanced:
    """Settings shown under "고급"."""

    show_unverified_items: bool = False  # items without a fitted display threshold (marked "참고용")
    count_in_beats: int = 4
    preroll_s: float = 3.0  # accompaniment played before the phrase starts
    tail_s: float = 1.0  # recorded after the phrase ends
    coach_level: str = "beginner"  # beginner | intermediate | advanced (gyeol.coach.health restrictions)
    session_gap_min: float = 30.0  # takes further apart than this start a new practice session
    max_session_takes: int = 5  # takes compared together (habit vs one-off)
    audibility: bool = True  # rank by audibility (re-renders the take once per item)


@dataclass
class Settings:
    data_dir: str = field(default_factory=lambda: str(default_data_dir()))
    port: int = 8765  # http on this PC (and the certificate download on the LAN)
    https_port: int = 8766  # https for phones on the same Wi-Fi
    lan: bool = True  # listen on the LAN for phones
    threads: int = 0  # 0 = all CPU cores
    open_browser: bool = True
    advanced: Advanced = field(default_factory=Advanced)

    @property
    def data(self) -> Path:
        return Path(self.data_dir)

    def cpu_threads(self) -> int:
        return self.threads if self.threads > 0 else max(1, os.cpu_count() or 1)

    def to_dict(self) -> dict:
        return asdict(self)


_lock = threading.Lock()


def settings_path() -> Path:
    return config_dir() / "settings.json"


def load_settings() -> Settings:
    """Settings from the file; ``GYEOL_STUDIO_DATA`` (set by ``--data-dir``) overrides the data folder for this run,
    including the worker processes, which read the settings themselves."""
    p = settings_path()
    s = Settings()
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            adv = Advanced(**{k: v for k, v in (raw.pop("advanced", None) or {}).items() if k in Advanced.__dataclass_fields__})
            s = Settings(**{k: v for k, v in raw.items() if k in Settings.__dataclass_fields__ and k != "advanced"}, advanced=adv)
        except (OSError, ValueError, TypeError):
            s = Settings()
    if os.environ.get("GYEOL_STUDIO_DATA"):
        s.data_dir = os.environ["GYEOL_STUDIO_DATA"]
    return s


def save_settings(s: Settings) -> None:
    with _lock:
        p = settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(s.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)


class Layout:
    """Where things live inside the data folder."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    @property
    def db(self) -> Path:
        return self.root / "studio.db"

    def song_dir(self, song_id: str) -> Path:
        return self.root / "songs" / song_id

    def phrase_dir(self, phrase_id: str) -> Path:
        return self.root / "phrases" / phrase_id

    def take_path(self, user_id: str, take_id: str) -> Path:
        return self.root / "takes" / user_id / f"{take_id}.wav"

    def demo_dir(self, take_id: str, item_slug: str) -> Path:
        return self.root / "demos" / take_id / item_slug

    def check_dir(self, user_id: str) -> Path:
        return self.root / "checks" / user_id

    @property
    def separation_cache(self) -> Path:
        return self.root / "cache" / "separation"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def training(self) -> Path:
        return self.root / "training"

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def ensure(self) -> None:
        for d in (self.root, self.root / "songs", self.root / "phrases", self.root / "takes", self.root / "demos",
                  self.separation_cache, self.exports, self.training, self.config, self.logs):
            d.mkdir(parents=True, exist_ok=True)
