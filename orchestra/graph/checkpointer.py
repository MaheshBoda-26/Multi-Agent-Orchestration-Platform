"""LangGraph Postgres checkpointer setup.

Uses psycopg3, not the app's asyncpg pool: ``AsyncPostgresSaver`` requires a
psycopg connection/pool, so this module owns a small ``AsyncConnectionPool``
alongside the asyncpg pool used by the rest of the app.
"""
import logging
import os
from typing import Any, Dict, Optional, Tuple

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

DEFAULT_DSN = "postgresql://orchestra:orchestra@localhost:5432/orchestra"


async def create_checkpointer(
    conn_string: Optional[str] = None,
) -> Tuple[AsyncConnectionPool[AsyncConnection[Dict[str, Any]]], AsyncPostgresSaver]:
    """Open a psycopg pool and return (pool, saver) with checkpoint tables set up.

    The pool is returned so the caller can close it; the saver is what the
    graph compiles with. ``setup()`` is idempotent, so calling this on every
    worker start is safe.
    """
    dsn: str = conn_string or os.getenv("DATABASE_URL") or DEFAULT_DSN
    pool: AsyncConnectionPool[AsyncConnection[Dict[str, Any]]] = AsyncConnectionPool(
        conninfo=dsn,
        min_size=1,
        max_size=4,
        open=False,
        # The saver expects autocommit connections with dict rows.
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    await pool.open()
    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    logger.info("LangGraph checkpointer ready on %s", dsn.split("@")[-1])
    return pool, saver
