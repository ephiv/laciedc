import json
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

# Fix 1 — allowlist prevents SQL injection via f-string column interpolation.
# asyncpg cannot parameterise column names, so the f-string stays, but only
# known schema-valid keys can ever reach it.
_ALLOWED_SETTING_KEYS: frozenset[str] = frozenset({
    "prefix", "log_channel_id",
    "auto_mod_enabled", "max_warns", "warn_action",
    "filter_profanity", "filter_spam", "filter_invites",
    "filter_links", "filter_caps", "filter_mentions",
    "caps_threshold", "mention_threshold", "spam_threshold",
    "starboard_channel_id", "starboard_threshold", "emoji_weights",
})


class Database:
    def __init__(self):
        self.pool: asyncpg.Pool | None = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "laciedc"),
            min_size=2,
            max_size=10,
        )
        await self.init_schema()

    async def init_schema(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guilds (
                    guild_id             BIGINT PRIMARY KEY,
                    prefix               TEXT DEFAULT '!',
                    log_channel_id       BIGINT,
                    auto_mod_enabled     BOOLEAN DEFAULT true,
                    max_warns            INT DEFAULT 3,
                    warn_action          VARCHAR(20) DEFAULT 'timeout',
                    filter_profanity     BOOLEAN DEFAULT true,
                    filter_spam          BOOLEAN DEFAULT true,
                    filter_invites       BOOLEAN DEFAULT true,
                    filter_links         BOOLEAN DEFAULT false,
                    filter_caps          BOOLEAN DEFAULT false,
                    filter_mentions      BOOLEAN DEFAULT true,
                    caps_threshold       INT DEFAULT 15,
                    mention_threshold    INT DEFAULT 5,
                    spam_threshold       INT DEFAULT 3,
                    created_at           TIMESTAMP DEFAULT NOW()
                )
            """)

            await conn.execute("""
                ALTER TABLE guilds
                    ADD COLUMN IF NOT EXISTS starboard_channel_id BIGINT,
                    ADD COLUMN IF NOT EXISTS starboard_threshold   INT  DEFAULT 5,
                    ADD COLUMN IF NOT EXISTS emoji_weights         TEXT DEFAULT '{"⭐": 1}'
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS warns (
                    id         SERIAL PRIMARY KEY,
                    guild_id   BIGINT REFERENCES guilds(guild_id),
                    user_id    BIGINT,
                    reason     TEXT,
                    severity   VARCHAR(20) DEFAULT 'medium',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bans (
                    id         SERIAL PRIMARY KEY,
                    guild_id   BIGINT REFERENCES guilds(guild_id),
                    user_id    BIGINT,
                    reason     TEXT,
                    banned_by  BIGINT,
                    is_active  BOOLEAN DEFAULT true,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS appeals (
                    id          SERIAL PRIMARY KEY,
                    guild_id    BIGINT REFERENCES guilds(guild_id),
                    user_id     BIGINT,
                    ban_id      INTEGER REFERENCES bans(id),
                    message     TEXT,
                    status      VARCHAR(20) DEFAULT 'pending',
                    reviewed_by BIGINT,
                    reviewed_at TIMESTAMP,
                    created_at  TIMESTAMP DEFAULT NOW()
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS spam_cache (
                    user_id      BIGINT,
                    guild_id     BIGINT,
                    message_hash TEXT,
                    created_at   TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (user_id, guild_id, message_hash)
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS starboard_posts (
                    message_id           BIGINT NOT NULL,
                    guild_id             BIGINT NOT NULL,
                    channel_id           BIGINT NOT NULL,
                    starboard_message_id BIGINT NOT NULL,
                    PRIMARY KEY (message_id, guild_id)
                )
            """)

    async def close(self):
        if self.pool:
            await self.pool.close()

    # ── Guild settings ─────────────────────────────────────────────────── #

    async def get_guild_settings(self, guild_id: int) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM guilds WHERE guild_id = $1", guild_id
            )
            if not row:
                await conn.execute(
                    "INSERT INTO guilds (guild_id) VALUES ($1)", guild_id
                )
                row = await conn.fetchrow(
                    "SELECT * FROM guilds WHERE guild_id = $1", guild_id
                )
            return dict(row)

    async def update_guild_setting(self, guild_id: int, key: str, value):
        # Fix 1 — reject unknown keys before they touch the query
        if key not in _ALLOWED_SETTING_KEYS:
            raise ValueError(f"unknown setting key: {key!r}")
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"UPDATE guilds SET {key} = $1 WHERE guild_id = $2",
                value, guild_id,
            )

    # ── Warnings ───────────────────────────────────────────────────────── #

    async def add_warn(
        self, guild_id: int, user_id: int, reason: str, severity: str = "medium"
    ) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """INSERT INTO warns (guild_id, user_id, reason, severity)
                   VALUES ($1, $2, $3, $4) RETURNING id""",
                guild_id, user_id, reason, severity,
            )

    async def get_warn_count(self, guild_id: int, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM warns WHERE guild_id = $1 AND user_id = $2",
                guild_id, user_id,
            )

    async def get_warns(self, guild_id: int, user_id: int) -> list:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM warns WHERE guild_id = $1 AND user_id = $2
                   ORDER BY created_at DESC""",
                guild_id, user_id,
            )
            return [dict(r) for r in rows]

    async def clear_warns(self, guild_id: int, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.execute(
                "DELETE FROM warns WHERE guild_id = $1 AND user_id = $2",
                guild_id, user_id,
            )

    # ── Bans ───────────────────────────────────────────────────────────── #

    async def add_ban(
        self, guild_id: int, user_id: int, reason: str, banned_by: int
    ) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """INSERT INTO bans (guild_id, user_id, reason, banned_by)
                   VALUES ($1, $2, $3, $4) RETURNING id""",
                guild_id, user_id, reason, banned_by,
            )

    async def get_active_ban(self, guild_id: int, user_id: int) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT * FROM bans WHERE guild_id = $1 AND user_id = $2
                   AND is_active = true""",
                guild_id, user_id,
            )
            return dict(row) if row else None

    async def deactivate_ban(self, ban_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE bans SET is_active = false WHERE id = $1", ban_id
            )

    # ── Appeals ────────────────────────────────────────────────────────── #

    async def add_appeal(
        self, guild_id: int, user_id: int, ban_id: int, message: str
    ) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """INSERT INTO appeals (guild_id, user_id, ban_id, message)
                   VALUES ($1, $2, $3, $4) RETURNING id""",
                guild_id, user_id, ban_id, message,
            )

    async def get_pending_appeals(self, guild_id: int) -> list:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT a.*, b.reason as ban_reason
                   FROM appeals a
                   JOIN bans b ON a.ban_id = b.id
                   WHERE a.guild_id = $1 AND a.status = 'pending'
                   ORDER BY a.created_at DESC""",
                guild_id,
            )
            return [dict(r) for r in rows]

    async def get_appeal(self, appeal_id: int) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT a.*, b.reason as ban_reason, b.created_at as ban_created
                   FROM appeals a
                   JOIN bans b ON a.ban_id = b.id
                   WHERE a.id = $1""",
                appeal_id,
            )
            return dict(row) if row else None

    async def update_appeal(self, appeal_id: int, status: str, reviewed_by: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE appeals SET status = $1, reviewed_by = $2,
                   reviewed_at = NOW() WHERE id = $3""",
                status, reviewed_by, appeal_id,
            )

    # ── Starboard ──────────────────────────────────────────────────────── #

    async def get_starboard_post(self, guild_id: int, message_id: int) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT * FROM starboard_posts
                   WHERE guild_id = $1 AND message_id = $2""",
                guild_id, message_id,
            )
            return dict(row) if row else None

    async def add_starboard_post(
        self, guild_id: int, message_id: int, channel_id: int, starboard_message_id: int,
    ):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO starboard_posts
                       (message_id, guild_id, channel_id, starboard_message_id)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT DO NOTHING""",
                message_id, guild_id, channel_id, starboard_message_id,
            )

    async def delete_starboard_post(self, guild_id: int, message_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM starboard_posts WHERE guild_id = $1 AND message_id = $2",
                guild_id, message_id,
            )


db = Database()
