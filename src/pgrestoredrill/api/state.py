"""Per-app settings and metadata engine."""

from __future__ import annotations

from dataclasses import dataclass
from weakref import WeakKeyDictionary

from fastapi import FastAPI
from sqlalchemy import Engine

from pgrestoredrill.config import Settings


@dataclass
class AppState:
    settings: Settings
    engine: Engine | None = None


_APPS: WeakKeyDictionary[FastAPI, AppState] = WeakKeyDictionary()


def remember(app: FastAPI, settings: Settings) -> AppState:
    state = AppState(settings=settings)
    _APPS[app] = state
    return state


def get_state(app: FastAPI) -> AppState:
    return _APPS[app]
