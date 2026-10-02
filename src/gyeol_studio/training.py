"""Training runs: the data a run may use, its config for ``gyeol train heads``, and reading its progress and report.

A run lives in ``<data>/training/runs/<id>/``:

* ``data/``    — the training export (``recordings.json`` + ``manifest.json``) taken when the run starts;
* ``config.yaml`` — the ``gyeol.train`` config (task ``heads``: register and phonation from the app's labels);
* ``cache/``   — data prepared by gyeol (``gyeol prepare``: pitch, curves, DSP features), resumable;
* ``out/``     — gyeol's run folder: training state, ``best.pt``, logs, ``report.json`` (test on unseen singers).
"""

from __future__ import annotations

import re
from pathlib import Path

PRESETS = {
    "quick": {"label": "빠르게 (몇 분)", "max_steps": 200, "val_every": 25, "save_every": 25, "log_every": 5, "patience": 6},
    "thorough": {"label": "꼼꼼하게 (30분 이상)", "max_steps": 3000, "val_every": 100, "save_every": 100, "log_every": 20, "patience": 10},
}
MIN_SINGERS = 3  # gyeol splits by singer: train / validation / test each need at least one person

METRIC_LABEL = {
    "test_register_acc": "발성(흉성·믹스·가성) 맞힌 비율",
    "test_phonation_acc": "음질(숨섞임 등) 맞힌 비율",
    "test_register_ece": "발성 확신도 오차 (낮을수록 좋음)",
    "test_phonation_ece": "음질 확신도 오차 (낮을수록 좋음)",
    "test_loss": "평가 손실 (낮을수록 좋음)",
    "register_acc": "발성 맞힌 비율 (검증)",
    "phonation_acc": "음질 맞힌 비율 (검증)",
    "loss": "검증 손실 (낮을수록 좋음)",
}


def run_dir(layout, run_id: str) -> Path:
    return layout.training / "runs" / run_id


def config(run_path: Path, preset: str, threads: int) -> dict:
    p = PRESETS[preset]
    return {
        "task": "heads", "seed": 0, "device": "auto", "threads": threads,
        "data": {
            "cache": str(run_path / "cache"),
            "manifests": [str(run_path / "data" / "manifest.json")],
            "prepare": {"sr": 44100, "hop": 512, "separation": "off", "features": ["dsp"], "max_seconds": 30.0},
            "split": {"train": 0.6, "val": 0.2, "test": 0.2},
            "crop_frames": [64, 192], "batch_size": 8,
        },
        "optim": {"lr": 1.0e-3, "weight_decay": 1.0e-4, "grad_clip": 1.0, "schedule": "cosine", "warmup_steps": 10, "betas": [0.9, 0.99]},
        "run": {"out": str(run_path / "out"), "max_steps": p["max_steps"], "val_every": p["val_every"], "save_every": p["save_every"],
                "log_every": p["log_every"], "patience": p["patience"]},
        "model": {"features": "dsp", "hidden": 64, "dropout": 0.1},
        "components": {"heads": "scratch"},
    }


_TRAIN = re.compile(r"\[train\] step (\d+)/(\d+).*ETA (\d+):(\d+):(\d+)")
_VAL = re.compile(r"\[val\] step (\d+): (.*)")


def parse_log(line: str) -> dict | None:
    """One line of gyeol's training log → {"kind": "train"|"val"|"prepare"|"other", …}."""
    m = _TRAIN.search(line)
    if m:
        step, total, hh, mm, ss = (int(x) for x in m.groups())
        return {"kind": "train", "step": step, "total": total, "eta_s": hh * 3600 + mm * 60 + ss}
    m = _VAL.search(line)
    if m:
        metrics = {}
        for part in m.group(2).replace("*best*", "").split(","):
            kv = part.strip().split(" ")
            if len(kv) == 2:
                try:
                    metrics[kv[0]] = float(kv[1])
                except ValueError:
                    pass
        return {"kind": "val", "step": int(m.group(1)), "metrics": metrics, "best": "*best*" in line}
    if line.startswith("[gyeol prepare]"):
        return {"kind": "prepare", "text": line}
    return {"kind": "other", "text": line}
