"""Apply pending SQL migrations in order and record applied versions."""
import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS migrations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    version INT NOT NULL,
    applied_at TIMESTAMPTZ DEFAULT NOW()
)
"""


async def run_migrations(pool: asyncpg.Pool) -> None:
    """Apply every migration file that has not been applied yet."""
    async with pool.acquire() as conn:
        await conn.execute(_CREATE_MIGRATIONS_TABLE)

        applied = await conn.fetch("SELECT name FROM migrations")
        applied_names = {row["name"] for row in applied}

        for migration_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            name = migration_file.stem
            if name in applied_names:
                logger.debug("Migration %s already applied, skipping", name)
                continue

            logger.info("Applying migration: %s", name)
            await conn.execute(migration_file.read_text())

            version = int(name.split("_")[0])
            await conn.execute(
                "INSERT INTO migrations (name, version) VALUES ($1, $2) "
                "ON CONFLICT (name) DO NOTHING",
                name,
                version,
            )
            logger.info("Applied migration: %s", name)


async def get_applied_migrations(pool: asyncpg.Pool) -> list[str]:
    """Return applied migration names, oldest first."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT name FROM migrations ORDER BY version")
        return [row["name"] for row in rows]
