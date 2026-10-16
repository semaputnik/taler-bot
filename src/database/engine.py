from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from src.config.settings import Settings
from src.database.errors import translate_db_error


def install_error_translation(engine: AsyncEngine) -> None:
    """Make every database error on this engine surface as an app exception.

    An engine-level `handle_error` event is the one place that sees reads, writes and
    commit alike, whichever session or Unit of Work runs them. Wrapping the session
    instead would mean overriding each of its entry points (execute, get, flush, commit, ...).
    """
    event.listen(engine.sync_engine, "handle_error", translate_db_error)


def create_engine(settings: Settings) -> AsyncEngine:
    engine = create_async_engine(str(settings.database.url), pool_pre_ping=True)
    install_error_translation(engine)
    return engine


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
