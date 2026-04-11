import sqlite3
from datetime import datetime
from typing import Optional
import json
import os

DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS infractions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            reason TEXT,
            moderator_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            guild_id INTEGER PRIMARY KEY,
            muted_role_id INTEGER,
            log_channel_id INTEGER,
            automod_enabled INTEGER DEFAULT 1,
            word_blacklist TEXT DEFAULT '[]',
            link_whitelist TEXT DEFAULT '[]',
            link_blocking_enabled INTEGER DEFAULT 1,
            spam_threshold INTEGER DEFAULT 5,
            mention_threshold INTEGER DEFAULT 3
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_infractions_user 
        ON infractions(user_id, guild_id)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS xp_data (
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 0,
            messages_sent INTEGER DEFAULT 0,
            voice_seconds INTEGER DEFAULT 0,
            last_message_time DATETIME,
            last_daily_bonus DATETIME,
            is_excluded INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, guild_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS level_roles (
            guild_id INTEGER NOT NULL,
            level INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, level)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS level_role_configs (
            guild_id INTEGER NOT NULL,
            level INTEGER NOT NULL,
            role_name TEXT,
            role_color INTEGER,
            is_enabled INTEGER DEFAULT 0,
            created_role_id INTEGER,
            PRIMARY KEY (guild_id, level)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_xp_guild ON xp_data(xp DESC, guild_id)
    """)

    conn.commit()
    conn.close()


def add_infraction(user_id: int, guild_id: int, infraction_type: str, 
                   moderator_id: int, reason: Optional[str] = None) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO infractions (user_id, guild_id, type, reason, moderator_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, guild_id, infraction_type, reason, moderator_id, datetime.utcnow())
    )
    infraction_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return infraction_id


def get_infraction_history(user_id: int, guild_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM infractions 
        WHERE user_id = ? AND guild_id = ?
        ORDER BY created_at DESC
        """,
        (user_id, guild_id)
    )
    results = cursor.fetchall()
    conn.close()
    return results


def get_infraction_count(user_id: int, guild_id: int, infraction_type: Optional[str] = None) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    if infraction_type:
        cursor.execute(
            """
            SELECT COUNT(*) FROM infractions 
            WHERE user_id = ? AND guild_id = ? AND type = ?
            """,
            (user_id, guild_id, infraction_type)
        )
    else:
        cursor.execute(
            """
            SELECT COUNT(*) FROM infractions 
            WHERE user_id = ? AND guild_id = ?
            """,
            (user_id, guild_id)
        )
    count = cursor.fetchone()[0]
    conn.close()
    return count


def clear_warnings(user_id: int, guild_id: int) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        DELETE FROM infractions 
        WHERE user_id = ? AND guild_id = ? AND type = 'warn'
        """,
        (user_id, guild_id)
    )
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted


def delete_infraction(infraction_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM infractions WHERE id = ?", (infraction_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_settings(guild_id: int) -> Optional[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM settings WHERE guild_id = ?", (guild_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def update_settings(guild_id: int, **kwargs):
    conn = get_connection()
    cursor = conn.cursor()
    
    existing = get_settings(guild_id)
    if not existing:
        cursor.execute(
            "INSERT INTO settings (guild_id) VALUES (?)",
            (guild_id,)
        )
    
    for key, value in kwargs.items():
        cursor.execute(
            f"UPDATE settings SET {key} = ? WHERE guild_id = ?",
            (value, guild_id)
        )
    
    conn.commit()
    conn.close()


def get_guild_settings(guild_id: int) -> dict:
    defaults = {
        "guild_id": guild_id,
        "muted_role_id": None,
        "log_channel_id": None,
        "automod_enabled": 1,
        "word_blacklist": "[]",
        "link_whitelist": "[]",
        "link_blocking_enabled": 1,
        "spam_threshold": 5,
        "mention_threshold": 3
    }
    
    stored = get_settings(guild_id)
    if stored:
        defaults.update(stored)
    
    return defaults


def get_word_blacklist(guild_id: int) -> list[str]:
    settings = get_guild_settings(guild_id)
    try:
        return json.loads(settings.get("word_blacklist", "[]"))
    except (json.JSONDecodeError, TypeError):
        return []


def get_link_whitelist(guild_id: int) -> list[str]:
    settings = get_guild_settings(guild_id)
    try:
        return json.loads(settings.get("link_whitelist", "[]"))
    except (json.JSONDecodeError, TypeError):
        return []


def add_word_to_blacklist(guild_id: int, word: str) -> bool:
    words = get_word_blacklist(guild_id)
    word_lower = word.lower()
    if word_lower not in words:
        words.append(word_lower)
        update_settings(guild_id, word_blacklist=json.dumps(words))
        return True
    return False


def remove_word_from_blacklist(guild_id: int, word: str) -> bool:
    words = get_word_blacklist(guild_id)
    word_lower = word.lower()
    if word_lower in words:
        words.remove(word_lower)
        update_settings(guild_id, word_blacklist=json.dumps(words))
        return True
    return False


def add_domain_to_whitelist(guild_id: int, domain: str) -> bool:
    domains = get_link_whitelist(guild_id)
    domain_lower = domain.lower()
    if domain_lower not in domains:
        domains.append(domain_lower)
        update_settings(guild_id, link_whitelist=json.dumps(domains))
        return True
    return False


def remove_domain_from_whitelist(guild_id: int, domain: str) -> bool:
    domains = get_link_whitelist(guild_id)
    domain_lower = domain.lower()
    if domain_lower in domains:
        domains.remove(domain_lower)
        update_settings(guild_id, link_whitelist=json.dumps(domains))
        return True
    return False


def get_xp_data(user_id: int, guild_id: int) -> Optional[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM xp_data WHERE user_id = ? AND guild_id = ?",
        (user_id, guild_id)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def create_xp_data(user_id: int, guild_id: int) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO xp_data (user_id, guild_id) VALUES (?, ?)",
        (user_id, guild_id)
    )
    conn.commit()
    conn.close()
    return get_xp_data(user_id, guild_id)


def add_xp(user_id: int, guild_id: int, amount: int) -> dict:
    create_xp_data(user_id, guild_id)
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE xp_data SET xp = xp + ? WHERE user_id = ? AND guild_id = ?",
        (amount, user_id, guild_id)
    )
    conn.commit()
    conn.close()
    
    return get_xp_data(user_id, guild_id)


def update_xp_level(user_id: int, guild_id: int, xp: int, level: int) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE xp_data SET xp = ?, level = ? WHERE user_id = ? AND guild_id = ?",
        (xp, level, user_id, guild_id)
    )
    conn.commit()
    conn.close()
    return get_xp_data(user_id, guild_id)


def increment_message_count(user_id: int, guild_id: int) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE xp_data SET messages_sent = messages_sent + 1, last_message_time = ? WHERE user_id = ? AND guild_id = ?",
        (datetime.utcnow(), user_id, guild_id)
    )
    conn.commit()
    conn.close()


def update_last_daily_bonus(user_id: int, guild_id: int) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE xp_data SET last_daily_bonus = ? WHERE user_id = ? AND guild_id = ?",
        (datetime.utcnow(), user_id, guild_id)
    )
    conn.commit()
    conn.close()


def update_voice_seconds(user_id: int, guild_id: int, additional_seconds: int) -> None:
    create_xp_data(user_id, guild_id)
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE xp_data SET voice_seconds = voice_seconds + ? WHERE user_id = ? AND guild_id = ?",
        (additional_seconds, user_id, guild_id)
    )
    conn.commit()
    conn.close()


def set_xp_excluded(user_id: int, guild_id: int, excluded: bool) -> None:
    create_xp_data(user_id, guild_id)
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE xp_data SET is_excluded = ? WHERE user_id = ? AND guild_id = ?",
        (1 if excluded else 0, user_id, guild_id)
    )
    conn.commit()
    conn.close()


def get_xp_leaderboard(guild_id: int, limit: int = 10) -> list[sqlite3.Row]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT user_id, xp, level, messages_sent, voice_seconds 
        FROM xp_data 
        WHERE guild_id = ? AND is_excluded = 0 
        ORDER BY xp DESC 
        LIMIT ?
        """,
        (guild_id, limit)
    )
    results = cursor.fetchall()
    conn.close()
    return results


def get_user_rank(user_id: int, guild_id: int) -> tuple[int, int]:
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT xp FROM xp_data WHERE user_id = ? AND guild_id = ? AND is_excluded = 0",
        (user_id, guild_id)
    )
    user_row = cursor.fetchone()
    
    if not user_row:
        conn.close()
        return (0, 0)
    
    user_xp = user_row[0]
    
    cursor.execute(
        "SELECT COUNT(*) + 1 FROM xp_data WHERE guild_id = ? AND xp > ? AND is_excluded = 0",
        (guild_id, user_xp)
    )
    rank = cursor.fetchone()[0]
    conn.close()
    
    return (rank, user_xp)


def set_level_role(guild_id: int, level: int, role_id: int) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?)",
        (guild_id, level, role_id)
    )
    conn.commit()
    conn.close()


def remove_level_role(guild_id: int, level: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM level_roles WHERE guild_id = ? AND level = ?",
        (guild_id, level)
    )
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_level_role(guild_id: int, level: int) -> Optional[int]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role_id FROM level_roles WHERE guild_id = ? AND level = ?",
        (guild_id, level)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return None


def get_all_level_roles(guild_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level ASC",
        (guild_id,)
    )
    results = cursor.fetchall()
    conn.close()
    return results


def get_user_total_xp(guild_id: int) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM xp_data WHERE guild_id = ? AND is_excluded = 0",
        (guild_id,)
    )
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_level_role_configs(guild_id: int) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT level, role_name, role_color, is_enabled, created_role_id FROM level_role_configs WHERE guild_id = ? ORDER BY level ASC",
        (guild_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_level_role_config(guild_id: int, level: int) -> Optional[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT level, role_name, role_color, is_enabled, created_role_id FROM level_role_configs WHERE guild_id = ? AND level = ?",
        (guild_id, level)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def set_level_role_config(guild_id: int, level: int, role_name: str, role_color: int, is_enabled: bool, created_role_id: int = None) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO level_role_configs (guild_id, level, role_name, role_color, is_enabled, created_role_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (guild_id, level, role_name, role_color, 1 if is_enabled else 0, created_role_id)
    )
    conn.commit()
    conn.close()


def delete_level_role_config(guild_id: int, level: int) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM level_role_configs WHERE guild_id = ? AND level = ?",
        (guild_id, level)
    )
    conn.commit()
    conn.close()


def get_enabled_level_roles(guild_id: int) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT level, role_name, role_color, created_role_id FROM level_role_configs WHERE guild_id = ? AND is_enabled = 1 ORDER BY level ASC",
        (guild_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


init_database()


async def setup(bot):
    pass
