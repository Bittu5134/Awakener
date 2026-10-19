"""SQLite persistence: schema, migration, and CRUD helpers.

Cooldown is stored in seconds internally; admins configure it in minutes.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Coroutine

import aiosqlite

from . import config

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id      INTEGER PRIMARY KEY,
    channel_id    INTEGER,
    role_id       INTEGER,
    cooldown_secs INTEGER NOT NULL DEFAULT {default_secs},
    perks_text    TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS guild_state (
    guild_id          INTEGER PRIMARY KEY,
    last_message_ts   TEXT,
    current_holder_id INTEGER
);
""".format(default_secs=config.DEFAULT_COOLDOWN_SECS)


@dataclass
class GuildConfig:
    guild_id: int
    channel_id: int | None = None
    role_id: int | None = None
    cooldown_secs: int = config.DEFAULT_COOLDOWN_SECS
    perks_text: str = ""

    @property
    def perks(self) -> list[str]:
        return [line.strip() for line in self.perks_text.splitlines() if line.strip()]


@dataclass
class GuildState:
    guild_id: int
    last_message_ts: datetime | None = None
    current_holder_id: int | None = None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed


async def open_db(path) -> aiosqlite.Connection:
    """Open the database, apply schema, and migrate legacy layouts."""
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.executescript(SCHEMA)
    await db.commit()
    await _migrate_cooldown_seconds(db)
    return db


async def _table_columns(db: aiosqlite.Connection, table: str) -> set[str]:
    rows = await db.execute_fetchall(f"PRAGMA table_info({table})")
    return {row["name"] for row in rows}


async def _migrate_cooldown_seconds(db: aiosqlite.Connection) -> None:
    """Convert legacy cooldown_mins (minutes) to cooldown_secs (seconds)."""
    columns = await _table_columns(db, "guild_config")
    if "cooldown_secs" in columns or "cooldown_mins" not in columns:
        return

    log.info("Migrating guild_config from cooldown_mins to cooldown_secs...")
    await db.executescript("""
        ALTER TABLE guild_config RENAME TO guild_config_legacy;
        CREATE TABLE guild_config (
            guild_id      INTEGER PRIMARY KEY,
            channel_id    INTEGER,
            role_id       INTEGER,
            cooldown_secs INTEGER NOT NULL DEFAULT 3600,
            perks_text    TEXT    NOT NULL DEFAULT ''
        );
        INSERT INTO guild_config
            (guild_id, channel_id, role_id, cooldown_secs, perks_text)
        SELECT guild_id, channel_id, role_id, cooldown_mins * 60, perks_text
        FROM guild_config_legacy;
        DROP TABLE guild_config_legacy;
        """)
    await db.commit()
    log.info("Migration complete.")


def _row_to_config(row: aiosqlite.Row) -> GuildConfig:
    return GuildConfig(
        guild_id=row["guild_id"],
        channel_id=row["channel_id"],
        role_id=row["role_id"],
        cooldown_secs=row["cooldown_secs"],
        perks_text=row["perks_text"] or "",
    )


def _row_to_state(row: aiosqlite.Row) -> GuildState:
    return GuildState(
        guild_id=row["guild_id"],
        last_message_ts=_parse_iso(row["last_message_ts"]),
        current_holder_id=row["current_holder_id"],
    )


async def load_configs(db: aiosqlite.Connection) -> dict[int, GuildConfig]:
    rows = await db.execute_fetchall("SELECT * FROM guild_config")
    return {row["guild_id"]: _row_to_config(row) for row in rows}


async def load_states(db: aiosqlite.Connection) -> dict[int, GuildState]:
    rows = await db.execute_fetchall("SELECT * FROM guild_state")
    return {row["guild_id"]: _row_to_state(row) for row in rows}


async def save_config(db: aiosqlite.Connection, config_row: GuildConfig) -> None:
    await db.execute(
        """
        INSERT INTO guild_config
            (guild_id, channel_id, role_id, cooldown_secs, perks_text)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            channel_id    = excluded.channel_id,
            role_id       = excluded.role_id,
            cooldown_secs = excluded.cooldown_secs,
            perks_text    = excluded.perks_text
        """,
        (
            config_row.guild_id,
            config_row.channel_id,
            config_row.role_id,
            config_row.cooldown_secs,
            config_row.perks_text,
        ),
    )
    await db.commit()


async def save_state(db: aiosqlite.Connection, state: GuildState) -> None:
    await db.execute(
        """
        INSERT INTO guild_state (guild_id, last_message_ts, current_holder_id)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            last_message_ts   = excluded.last_message_ts,
            current_holder_id = excluded.current_holder_id
        """,
        (
            state.guild_id,
            state.last_message_ts.isoformat() if state.last_message_ts else None,
            state.current_holder_id,
        ),
    )
    await db.commit()


async def close_db(db: aiosqlite.Connection | None) -> None:
    if db is not None:
        await db.close()


__all__ = [
    "GuildConfig",
    "GuildState",
    "open_db",
    "close_db",
    "load_configs",
    "load_states",
    "save_config",
    "save_state",
]
