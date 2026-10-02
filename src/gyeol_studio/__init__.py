"""gyeol 스튜디오 — a local vocal-coaching app built on the gyeol library.

The server (FastAPI) runs on the user's PC; the screens are a web UI used from
the PC's browser or a phone on the same Wi-Fi.  All analysis goes through
``gyeol.api``; the coaching order and health checks come from ``gyeol.coach``.
"""

__version__ = "0.1.0"
