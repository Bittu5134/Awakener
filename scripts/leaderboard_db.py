import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS awaken_counts (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    count    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
"""


async def open_lb(path) -> aiosqlite.Connection:
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.executescript(SCHEMA)
    await db.commit()
    return db


async def close_lb(db: aiosqlite.Connection | None) -> None:
    if db is not None:
        await db.close()


async def increment(db: aiosqlite.Connection, guild_id: int, user_id: int) -> None:
    await db.execute(
        """
        INSERT INTO awaken_counts (guild_id, user_id, count)
        VALUES (?, ?, 1)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET count = count + 1
        """,
        (guild_id, user_id),
    )
    await db.commit()


async def top(
    db: aiosqlite.Connection, guild_id: int, limit: int
) -> list[tuple[int, int]]:
    rows = await db.execute_fetchall(
        """
        SELECT user_id, count FROM awaken_counts
        WHERE guild_id = ?
        ORDER BY count DESC, user_id ASC
        LIMIT ?
        """,
        (guild_id, limit),
    )
    return [(row["user_id"], row["count"]) for row in rows]


async def stats(
    db: aiosqlite.Connection, guild_id: int, user_id: int
) -> tuple[int | None, int]:
    """Return ``(rank, count)`` for one user, in the ordering ``top`` uses.

    ``rank`` is ``None`` when the user has no counted awakening yet, so
    callers can skip appending a row for them.
    """
    rows = await db.execute_fetchall(
        """
        SELECT count,
               (
                   SELECT COUNT(*) FROM awaken_counts AS other
                   WHERE other.guild_id = counts.guild_id
                     AND (
                         other.count > counts.count
                         OR (other.count = counts.count
                             AND other.user_id < counts.user_id)
                     )
               ) + 1 AS rank
        FROM awaken_counts AS counts
        WHERE guild_id = ? AND user_id = ?
        """,
        (guild_id, user_id),
    )
    if not rows or not rows[0]["count"]:
        return None, 0
    return rows[0]["rank"], rows[0]["count"]


async def all_rows(db: aiosqlite.Connection, guild_id: int) -> list[int]:
    rows = await db.execute_fetchall(
        "SELECT user_id FROM awaken_counts WHERE guild_id = ?", (guild_id,)
    )
    return [row["user_id"] for row in rows]


async def purge_missing(
    db: aiosqlite.Connection, guild_id: int, present_ids: list[int]
) -> None:
    if not present_ids:
        await db.execute("DELETE FROM awaken_counts WHERE guild_id = ?", (guild_id,))
    else:
        placeholders = ",".join("?" * len(present_ids))
        await db.execute(
            f"DELETE FROM awaken_counts WHERE guild_id = ? AND user_id NOT IN ({placeholders})",
            (guild_id, *present_ids),
        )
    await db.commit()


async def reset_guild(db: aiosqlite.Connection, guild_id: int) -> None:
    await db.execute("DELETE FROM awaken_counts WHERE guild_id = ?", (guild_id,))
    await db.commit()
