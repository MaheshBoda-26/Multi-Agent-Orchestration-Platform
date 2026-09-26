import os

import asyncpg
import pytest
import pytest_asyncio

from migrations import run_migrations

DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql://orchestra:orchestra@localhost:5432/orchestra"),
)


@pytest_asyncio.fixture
async def postgres_pool():
    """Real Postgres pool with migrations applied.

    Skips (rather than fails) when no database is reachable, so unit runs stay
    green on machines without the compose stack up.
    """
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres unavailable at {DATABASE_URL}: {exc}")

    assert pool is not None
    try:
        await run_migrations(pool)
        yield pool
    finally:
        await pool.close()
