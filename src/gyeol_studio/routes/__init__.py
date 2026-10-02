"""API routers."""

from __future__ import annotations

import importlib

from fastapi import FastAPI

MODULES = ("system", "users", "songs", "takes", "labels", "exports", "checks", "history", "training", "network")


def register_routes(app: FastAPI) -> None:
    for name in MODULES:
        try:
            mod = importlib.import_module(f"{__name__}.{name}")
        except ModuleNotFoundError as exc:  # routers of later phases are added as they are built
            if exc.name != f"{__name__}.{name}":
                raise
            continue
        app.include_router(mod.router)
