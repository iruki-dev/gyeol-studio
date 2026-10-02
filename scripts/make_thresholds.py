"""Build the display thresholds shipped with the app (``src/gyeol_studio/resources/thresholds.json``).

gyeol shows a coaching item only when its size exceeds its fitted measurement
uncertainty (``gyeol.coach.thresholds``) and ships no fitted set.  Until real
paired recordings exist, the app uses the set gyeol's own example fits on
synthetic knob-recovery data (``examples/fit_thresholds.py``); its provenance
says ``"synthetic": true`` and the coaching screen says so.

    python scripts/make_thresholds.py            # ~30 s on a laptop CPU

This is a build step, not part of the running app (see docs/library-requests.md).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# knob_recovery analyses with separation="auto" and has no switch for it: when BS-RoFormer weights are in gyeol's
# cache (~/.cache/gyeol) it separates the synthetic takes and the fitted set changes.  Point the home folder at an
# empty directory so the result does not depend on what this machine has fetched (docs/library-requests.md).
_home = tempfile.mkdtemp(prefix="gyeol-thresholds-")
os.environ["HOME"] = os.environ["USERPROFILE"] = _home

from gyeol.eval.knob_recovery import fit_from_knob_data, knob_recovery  # noqa: E402
from gyeol.pitch.adapters import PyinTracker, SHSTracker, YinTracker  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "src" / "gyeol_studio" / "resources" / "thresholds.json"


def main() -> int:
    data = knob_recovery(n_takes=8, seed=0, trackers=[PyinTracker(), YinTracker(), SHSTracker()])
    ts = fit_from_knob_data(data)
    for name, t in ts.thresholds.items():
        print(f"{name:18s} {'usable' if t.usable else 'not reliable'}  MDC95={t.mdc:.2f} {t.unit}")
    ts.to_json(OUT)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
