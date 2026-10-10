"""FastAPI application. No route starts a restore."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from pgrestoredrill import __version__
from pgrestoredrill.api.routes import router
from pgrestoredrill.api.state import get_state, remember
from pgrestoredrill.config import Settings
from pgrestoredrill.db.session import make_engine


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    state = get_state(app)
    engine = make_engine(state.settings.database_url)
    state.engine = engine
    try:
        yield
    finally:
        engine.dispose()
        state.engine = None


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = Settings() if settings is None else settings
    app = FastAPI(title="pgrestoredrill", version=__version__, lifespan=_lifespan)
    remember(app, resolved)
    app.include_router(router)
    return app
