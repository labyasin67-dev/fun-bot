"""SQLite persistence for guild settings, levels, self-roles, voice, mod, alts, and premium."""

from __future__ import annotations

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY,
    welcome_channel_id INTEGER,
    welcome_message TEXT,
    counting_channel_id INTEGER,
    counting_next INTEGER NOT NULL DEFAULT 1,
    counting_last_user INTEGER,
    counting_high INTEGER NOT NULL DEFAULT 0,
    levelup_channel_id INTEGER,
    jtc_channel_id INTEGER,
    jtc_category_id INTEGER,
    ban_dm_enabled INTEGER NOT NULL DEFAULT 0,
    ban_dm_message TEXT,
    ban_announce_enabled INTEGER NOT NULL DEFAULT 0,
    ban_announce_message TEXT,
    ban_announce_channel_id INTEGER,
    leave_enabled INTEGER NOT NULL DEFAULT 0,
    leave_message TEXT,
    leave_channel_id INTEGER
);

CREATE TABLE IF NOT EXISTS members (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    xp INTEGER NOT NULL DEFAULT 0,
    voice_seconds INTEGER NOT NULL DEFAULT 0,
    last_message_xp REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS level_roles (
    guild_id INTEGER NOT NULL,
    level INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, level)
);

CREATE TABLE IF NOT EXISTS self_roles (
    guild_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    emoji TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS temp_voice (
    channel_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    panel_message_id INTEGER,
    locked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    reason TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS warning_removals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    warning_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    user_name TEXT,
    original_reason TEXT,
    removed_by INTEGER NOT NULL,
    removed_by_name TEXT,
    removal_reason TEXT,
    removed_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_warning_removals_guild ON warning_removals(guild_id, removed_at DESC);

CREATE TABLE IF NOT EXISTS guild_channels (
    guild_id INTEGER NOT NULL,
    feature TEXT NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, feature, channel_id)
);

CREATE TABLE IF NOT EXISTS alt_config (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    log_channel_id INTEGER,
    min_age_days INTEGER NOT NULL DEFAULT 7,
    action TEXT NOT NULL DEFAULT 'log',
    quarantine_role_id INTEGER
);

CREATE TABLE IF NOT EXISTS alt_whitelist (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS alt_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER NOT NULL,
    verdict TEXT NOT NULL,
    reasons TEXT NOT NULL,
    created_at REAL NOT NULL,
    username TEXT,
    display_name TEXT,
    avatar_url TEXT,
    account_created_at REAL,
    joined_at REAL,
    action_taken TEXT,
    action_by INTEGER,
    action_at REAL,
    status TEXT
);

CREATE TABLE IF NOT EXISTS alt_mod_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    account_created_at REAL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS disabled_games (
    guild_id INTEGER NOT NULL,
    game_key TEXT NOT NULL,
    PRIMARY KEY (guild_id, game_key)
);

CREATE TABLE IF NOT EXISTS mod_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    user_id INTEGER,
    moderator_id INTEGER,
    detail TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    payer_user_id INTEGER,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    plan TEXT,
    status TEXT NOT NULL,
    current_period_end REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_guild ON subscriptions(guild_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_subscriptions_stripe ON subscriptions(stripe_subscription_id)
    WHERE stripe_subscription_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS premium_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grant_type TEXT NOT NULL,
    guild_id INTEGER,
    user_id INTEGER,
    expires_at REAL,
    note TEXT,
    granted_by INTEGER,
    created_at REAL NOT NULL,
    revoked_at REAL
);

CREATE INDEX IF NOT EXISTS idx_grants_guild ON premium_grants(guild_id);
CREATE INDEX IF NOT EXISTS idx_grants_user ON premium_grants(user_id);

CREATE TABLE IF NOT EXISTS site_pages (
    key TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS customrole_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    min_level INTEGER NOT NULL DEFAULT 10,
    anchor_role_id INTEGER,
    give_enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS custom_roles (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    secondary_colour INTEGER,
    holder_id INTEGER,
    PRIMARY KEY (guild_id, user_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_custom_roles_role ON custom_roles(guild_id, role_id);

CREATE TABLE IF NOT EXISTS custom_role_restrictions (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    reason TEXT,
    by INTEGER,
    at REAL NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS custom_role_give_blocks (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    reason TEXT,
    by INTEGER,
    at REAL NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS profile_hidden_roles (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, role_id)
);

CREATE TABLE IF NOT EXISTS custom_role_perms (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    min_level INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS custom_role_perm_list (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    permission TEXT NOT NULL,
    PRIMARY KEY (guild_id, user_id, permission)
);

CREATE TABLE IF NOT EXISTS custom_role_global_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    min_level INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS custom_role_global_perms (
    guild_id INTEGER NOT NULL,
    permission TEXT NOT NULL,
    PRIMARY KEY (guild_id, permission)
);

CREATE TABLE IF NOT EXISTS report_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'channel',
    category_id INTEGER,
    alert_channel_id INTEGER,
    closed_channel_id INTEGER,
    staff_role_id INTEGER
);

CREATE TABLE IF NOT EXISTS report_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER,
    message_channel_id INTEGER,
    message_id INTEGER,
    announce_channel_id INTEGER,
    announce_message_id INTEGER,
    reporter_id INTEGER NOT NULL,
    reporter_name TEXT,
    reporter_avatar TEXT,
    reported_user_id INTEGER,
    reported_name TEXT,
    reported_avatar TEXT,
    message_link TEXT,
    message_preview TEXT,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    claimed_by INTEGER,
    claimed_by_name TEXT,
    claimed_by_avatar TEXT,
    claimed_at REAL,
    decided_by INTEGER,
    decided_by_name TEXT,
    decided_by_avatar TEXT,
    decided_at REAL,
    decision_reason TEXT,
    created_at REAL NOT NULL,
    closed_at REAL,
    closed_by INTEGER,
    closed_by_name TEXT,
    closed_by_avatar TEXT,
    reporter_dm_channel_id INTEGER,
    reporter_dm_message_id INTEGER
);
CREATE TABLE IF NOT EXISTS report_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    author_id INTEGER,
    author_name TEXT,
    author_avatar TEXT,
    body TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_report_notes_ticket ON report_notes(ticket_id, created_at);
CREATE INDEX IF NOT EXISTS idx_report_tickets_guild ON report_tickets(guild_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_report_tickets_reporter ON report_tickets(guild_id, reporter_id, status);

CREATE TABLE IF NOT EXISTS report_blocks (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    reason TEXT,
    by INTEGER,
    at REAL NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS youtube_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    channel_id INTEGER
);

CREATE TABLE IF NOT EXISTS youtube_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    video_url TEXT NOT NULL,
    scheduled_at REAL NOT NULL,
    posted INTEGER NOT NULL DEFAULT 0,
    posted_at REAL
);

CREATE TABLE IF NOT EXISTS fun_slaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    slapper_id INTEGER NOT NULL,
    slapped_id INTEGER NOT NULL,
    action TEXT NOT NULL DEFAULT 'slap',
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_youtube_schedule_guild ON youtube_schedule(guild_id, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_fun_slaps_guild ON fun_slaps(guild_id, slapped_id, action);

CREATE TABLE IF NOT EXISTS youtube_tokens (
    user_id INTEGER NOT NULL,
    guild_id INTEGER,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (user_id, guild_id)
);
CREATE INDEX IF NOT EXISTS idx_youtube_tokens_user ON youtube_tokens(user_id);
"""

FEATURE_SETTINGS_COLUMN = {
    "welcome": "welcome_channel_id",
    "levelups": "levelup_channel_id",
    "counting": "counting_channel_id",
}

KNOWN_FEATURES = ("alts", "modlog", "levelups", "welcome", "games", "counting")


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def setup(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._migrate_feature_channels()
        await self._migrate_alt_flags()
        await self._migrate_guild_settings_columns()
        await self._migrate_custom_roles_columns()
        await self._migrate_report_columns()
        await self._migrate_fun_slaps_columns()
        await self._migrate_warning_removals()
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Database.setup() was not called"
        return self._db

    # --- guild settings ---

    async def get_settings(self, guild_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        )
        return await cur.fetchone()

    async def ensure_settings(self, guild_id: int) -> aiosqlite.Row:
        row = await self.get_settings(guild_id)
        if row is None:
            await self.db.execute(
                "INSERT INTO guild_settings (guild_id) VALUES (?)", (guild_id,)
            )
            await self.db.commit()
            row = await self.get_settings(guild_id)
        assert row is not None
        return row

    async def update_settings(self, guild_id: int, **fields) -> None:
        await self.ensure_settings(guild_id)
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [guild_id]
        await self.db.execute(
            f"UPDATE guild_settings SET {cols} WHERE guild_id = ?", values
        )
        await self.db.commit()

    # --- members / XP ---

    async def get_member(self, guild_id: int, user_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM members WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return await cur.fetchone()

    async def ensure_member(self, guild_id: int, user_id: int) -> aiosqlite.Row:
        row = await self.get_member(guild_id, user_id)
        if row is None:
            await self.db.execute(
                "INSERT INTO members (guild_id, user_id) VALUES (?, ?)",
                (guild_id, user_id),
            )
            await self.db.commit()
            row = await self.get_member(guild_id, user_id)
        assert row is not None
        return row

    async def add_xp(self, guild_id: int, user_id: int, amount: int, *, message_ts: float | None = None) -> tuple[int, int]:
        """Add XP and return (old_xp, new_xp)."""
        await self.ensure_member(guild_id, user_id)
        row = await self.get_member(guild_id, user_id)
        old = int(row["xp"])
        if message_ts is not None:
            await self.db.execute(
                "UPDATE members SET xp = xp + ?, last_message_xp = ? WHERE guild_id = ? AND user_id = ?",
                (amount, message_ts, guild_id, user_id),
            )
        else:
            await self.db.execute(
                "UPDATE members SET xp = xp + ? WHERE guild_id = ? AND user_id = ?",
                (amount, guild_id, user_id),
            )
        await self.db.commit()
        return old, old + amount

    async def add_voice_xp_and_seconds(self, guild_id: int, user_id: int, xp_amount: int, seconds: int) -> tuple[int, int]:
        """Atomically add XP and voice seconds in a single transaction."""
        await self.ensure_member(guild_id, user_id)
        row = await self.get_member(guild_id, user_id)
        old = int(row["xp"])
        await self.db.execute(
            "UPDATE members SET xp = xp + ?, voice_seconds = voice_seconds + ? WHERE guild_id = ? AND user_id = ?",
            (xp_amount, seconds, guild_id, user_id),
        )
        await self.db.commit()
        return old, old + xp_amount

    async def set_xp(self, guild_id: int, user_id: int, xp: int) -> tuple[int, int]:
        """Set XP to an exact value (clamped at 0) and return (old_xp, new_xp)."""
        await self.ensure_member(guild_id, user_id)
        row = await self.get_member(guild_id, user_id)
        old = int(row["xp"])
        new = max(0, int(xp))
        await self.db.execute(
            "UPDATE members SET xp = ? WHERE guild_id = ? AND user_id = ?",
            (new, guild_id, user_id),
        )
        await self.db.commit()
        return old, new

    async def add_voice_seconds(self, guild_id: int, user_id: int, seconds: int) -> int:
        await self.ensure_member(guild_id, user_id)
        await self.db.execute(
            "UPDATE members SET voice_seconds = voice_seconds + ? WHERE guild_id = ? AND user_id = ?",
            (seconds, guild_id, user_id),
        )
        await self.db.commit()
        row = await self.get_member(guild_id, user_id)
        return int(row["voice_seconds"])

    async def top_xp(self, guild_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM members WHERE guild_id = ? ORDER BY xp DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cur.fetchall()

    async def top_voice(self, guild_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM members WHERE guild_id = ? ORDER BY voice_seconds DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cur.fetchall()

    async def xp_rank(self, guild_id: int, user_id: int) -> int:
        cur = await self.db.execute(
            """
            SELECT 1 + COUNT(*) FROM members
            WHERE guild_id = ? AND xp > COALESCE(
                (SELECT xp FROM members WHERE guild_id = ? AND user_id = ?), 0
            )
            """,
            (guild_id, guild_id, user_id),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 1

    async def voice_rank(self, guild_id: int, user_id: int) -> int:
        cur = await self.db.execute(
            """
            SELECT 1 + COUNT(*) FROM members
            WHERE guild_id = ? AND voice_seconds > COALESCE(
                (SELECT voice_seconds FROM members WHERE guild_id = ? AND user_id = ?), 0
            )
            """,
            (guild_id, guild_id, user_id),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 1

    # --- level roles ---

    async def set_level_role(self, guild_id: int, level: int, role_id: int) -> None:
        await self.db.execute(
            """
            INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?)
            ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id
            """,
            (guild_id, level, role_id),
        )
        await self.db.commit()

    async def remove_level_role(self, guild_id: int, level: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM level_roles WHERE guild_id = ? AND level = ?",
            (guild_id, level),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def level_roles(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM level_roles WHERE guild_id = ? ORDER BY level ASC",
            (guild_id,),
        )
        return await cur.fetchall()

    # --- self roles ---

    async def add_self_role(self, guild_id: int, role_id: int, label: str, emoji: str | None) -> None:
        cur = await self.db.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM self_roles WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cur.fetchone()
        order = int(row["n"]) if row else 1
        await self.db.execute(
            """
            INSERT INTO self_roles (guild_id, role_id, label, emoji, sort_order)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, role_id) DO UPDATE SET label = excluded.label, emoji = excluded.emoji
            """,
            (guild_id, role_id, label, emoji, order),
        )
        await self.db.commit()

    async def remove_self_role(self, guild_id: int, role_id: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM self_roles WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def self_roles(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM self_roles WHERE guild_id = ? ORDER BY sort_order ASC",
            (guild_id,),
        )
        return await cur.fetchall()

    # --- temp voice ---

    async def add_temp_voice(self, channel_id: int, guild_id: int, owner_id: int, panel_message_id: int | None = None) -> None:
        await self.db.execute(
            """
            INSERT INTO temp_voice (channel_id, guild_id, owner_id, panel_message_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                owner_id = excluded.owner_id,
                panel_message_id = excluded.panel_message_id
            """,
            (channel_id, guild_id, owner_id, panel_message_id),
        )
        await self.db.commit()

    async def get_temp_voice(self, channel_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM temp_voice WHERE channel_id = ?", (channel_id,)
        )
        return await cur.fetchone()

    async def temp_voice_for_owner(self, guild_id: int, owner_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM temp_voice WHERE guild_id = ? AND owner_id = ?",
            (guild_id, owner_id),
        )
        return await cur.fetchone()

    async def set_temp_owner(self, channel_id: int, owner_id: int) -> None:
        await self.db.execute(
            "UPDATE temp_voice SET owner_id = ? WHERE channel_id = ?",
            (owner_id, channel_id),
        )
        await self.db.commit()

    async def set_temp_locked(self, channel_id: int, locked: bool) -> None:
        await self.db.execute(
            "UPDATE temp_voice SET locked = ? WHERE channel_id = ?",
            (1 if locked else 0, channel_id),
        )
        await self.db.commit()

    async def set_panel_message(self, channel_id: int, message_id: int) -> None:
        await self.db.execute(
            "UPDATE temp_voice SET panel_message_id = ? WHERE channel_id = ?",
            (message_id, channel_id),
        )
        await self.db.commit()

    async def delete_temp_voice(self, channel_id: int) -> None:
        await self.db.execute(
            "DELETE FROM temp_voice WHERE channel_id = ?", (channel_id,)
        )
        await self.db.commit()

    async def all_temp_voice(self, guild_id: int | None = None) -> list[aiosqlite.Row]:
        if guild_id is None:
            cur = await self.db.execute("SELECT * FROM temp_voice")
        else:
            cur = await self.db.execute(
                "SELECT * FROM temp_voice WHERE guild_id = ?", (guild_id,)
            )
        return await cur.fetchall()

    async def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str | None) -> int:
        import time
        cur = await self.db.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, moderator_id, reason, time.time()),
        )
        await self.db.commit()
        return int(cur.lastrowid or 0)

    async def get_warnings(self, guild_id: int, user_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY created_at ASC",
            (guild_id, user_id),
        )
        return await cur.fetchall()

    async def _insert_warning_removal(
        self,
        row,
        *,
        removed_by: int,
        removed_by_name: str | None = None,
        user_name: str | None = None,
        removal_reason: str | None = None,
    ) -> None:
        import time
        await self.db.execute(
            """
            INSERT INTO warning_removals (
                guild_id, warning_id, user_id, user_name, original_reason,
                removed_by, removed_by_name, removal_reason, removed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(row["guild_id"]),
                int(row["id"]),
                int(row["user_id"]),
                user_name,
                row["reason"],
                int(removed_by),
                removed_by_name,
                removal_reason,
                time.time(),
            ),
        )

    async def clear_warnings(
        self,
        guild_id: int,
        user_id: int,
        *,
        removed_by: int,
        removed_by_name: str | None = None,
        user_name: str | None = None,
        removal_reason: str | None = None,
    ) -> int:
        rows = await self.get_warnings(guild_id, user_id)
        for row in rows:
            await self._insert_warning_removal(
                row,
                removed_by=removed_by,
                removed_by_name=removed_by_name,
                user_name=user_name,
                removal_reason=removal_reason,
            )
        cur = await self.db.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self.db.commit()
        return cur.rowcount

    async def delete_warning(
        self,
        guild_id: int,
        user_id: int,
        warning_id: int,
        *,
        removed_by: int,
        removed_by_name: str | None = None,
        user_name: str | None = None,
        removal_reason: str | None = None,
    ) -> bool:
        rows = await self.get_warnings(guild_id, user_id)
        row = next((r for r in rows if int(r["id"]) == int(warning_id)), None)
        if row is None:
            return False
        await self._insert_warning_removal(
            row,
            removed_by=removed_by,
            removed_by_name=removed_by_name,
            user_name=user_name,
            removal_reason=removal_reason,
        )
        cur = await self.db.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ? AND id = ?",
            (guild_id, user_id, int(warning_id)),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def delete_latest_warning(
        self,
        guild_id: int,
        user_id: int,
        *,
        removed_by: int,
        removed_by_name: str | None = None,
        user_name: str | None = None,
        removal_reason: str | None = None,
    ):
        rows = await self.get_warnings(guild_id, user_id)
        if not rows:
            return None
        latest = rows[-1]
        ok = await self.delete_warning(
            guild_id,
            user_id,
            int(latest["id"]),
            removed_by=removed_by,
            removed_by_name=removed_by_name,
            user_name=user_name,
            removal_reason=removal_reason,
        )
        return latest if ok else None

    async def list_warning_removals(self, guild_id: int, limit: int = 80) -> list:
        cur = await self.db.execute(
            "SELECT * FROM warning_removals WHERE guild_id = ? ORDER BY removed_at DESC LIMIT ?",
            (int(guild_id), int(limit)),
        )
        return await cur.fetchall()

    async def _migrate_warning_removals(self) -> None:
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS warning_removals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                warning_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT,
                original_reason TEXT,
                removed_by INTEGER NOT NULL,
                removed_by_name TEXT,
                removal_reason TEXT,
                removed_at REAL NOT NULL
            )
            """
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_warning_removals_guild ON warning_removals(guild_id, removed_at DESC)"
        )


    # --- feature channels (setchannel) ---

    async def _migrate_feature_channels(self) -> None:
        """Copy legacy guild_settings / alt_config channels into guild_channels once."""
        await self.db.execute(
            """
            INSERT OR IGNORE INTO guild_channels (guild_id, feature, channel_id)
            SELECT guild_id, 'welcome', welcome_channel_id
            FROM guild_settings WHERE welcome_channel_id IS NOT NULL
            """
        )
        await self.db.execute(
            """
            INSERT OR IGNORE INTO guild_channels (guild_id, feature, channel_id)
            SELECT guild_id, 'levelups', levelup_channel_id
            FROM guild_settings WHERE levelup_channel_id IS NOT NULL
            """
        )
        await self.db.execute(
            """
            INSERT OR IGNORE INTO guild_channels (guild_id, feature, channel_id)
            SELECT guild_id, 'counting', counting_channel_id
            FROM guild_settings WHERE counting_channel_id IS NOT NULL
            """
        )
        await self.db.execute(
            """
            INSERT OR IGNORE INTO guild_channels (guild_id, feature, channel_id)
            SELECT guild_id, 'alts', log_channel_id
            FROM alt_config WHERE log_channel_id IS NOT NULL
            """
        )


    async def _migrate_alt_flags(self) -> None:
        cur = await self.db.execute("PRAGMA table_info(alt_flags)")
        cols = {str(row[1]) for row in await cur.fetchall()}
        additions = {
            "username": "TEXT",
            "display_name": "TEXT",
            "avatar_url": "TEXT",
            "account_created_at": "REAL",
            "joined_at": "REAL",
            "action_taken": "TEXT",
            "action_by": "INTEGER",
            "action_at": "REAL",
            "status": "TEXT",
        }
        for name, typ in additions.items():
            if name not in cols:
                await self.db.execute(f"ALTER TABLE alt_flags ADD COLUMN {name} {typ}")
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_alt_flags_guild_created ON alt_flags(guild_id, created_at DESC)"
        )

    async def _migrate_guild_settings_columns(self) -> None:
        cur = await self.db.execute("PRAGMA table_info(guild_settings)")
        cols = {str(row[1]) for row in await cur.fetchall()}
        additions = {
            "ban_dm_enabled": "INTEGER NOT NULL DEFAULT 0",
            "ban_dm_message": "TEXT",
            "ban_announce_enabled": "INTEGER NOT NULL DEFAULT 0",
            "ban_announce_message": "TEXT",
            "ban_announce_channel_id": "INTEGER",
            "leave_enabled": "INTEGER NOT NULL DEFAULT 0",
            "leave_message": "TEXT",
            "leave_channel_id": "INTEGER",
        }
        for name, typ in additions.items():
            if name not in cols:
                await self.db.execute(f"ALTER TABLE guild_settings ADD COLUMN {name} {typ}")

    async def get_feature_channels(self, guild_id: int, feature: str, *, fallback: bool = True) -> list[int]:
        cur = await self.db.execute(
            "SELECT channel_id FROM guild_channels WHERE guild_id = ? AND feature = ? ORDER BY rowid",
            (guild_id, feature),
        )
        rows = await cur.fetchall()
        ids = [int(row["channel_id"]) for row in rows]
        if ids or not fallback:
            return ids
        # Fallback to legacy columns, then backfill so both stay in sync.
        if feature in FEATURE_SETTINGS_COLUMN:
            settings = await self.get_settings(guild_id)
            col = FEATURE_SETTINGS_COLUMN[feature]
            if settings and settings[col]:
                channel_id = int(settings[col])
                await self.db.execute(
                    "INSERT OR IGNORE INTO guild_channels (guild_id, feature, channel_id) VALUES (?, ?, ?)",
                    (guild_id, feature, channel_id),
                )
                await self.db.commit()
                return [channel_id]
        if feature == "alts":
            cfg = await self.get_alt_config(guild_id)
            if cfg and cfg["log_channel_id"]:
                channel_id = int(cfg["log_channel_id"])
                await self.db.execute(
                    "INSERT OR IGNORE INTO guild_channels (guild_id, feature, channel_id) VALUES (?, ?, ?)",
                    (guild_id, feature, channel_id),
                )
                await self.db.commit()
                return [channel_id]
        return []

    async def get_feature_channel(self, guild_id: int, feature: str) -> int | None:
        channels = await self.get_feature_channels(guild_id, feature)
        return channels[0] if channels else None

    async def list_feature_channels(self, guild_id: int) -> dict[str, list[int]]:
        cur = await self.db.execute(
            "SELECT feature, channel_id FROM guild_channels WHERE guild_id = ? ORDER BY feature, rowid",
            (guild_id,),
        )
        out: dict[str, list[int]] = {name: [] for name in KNOWN_FEATURES}
        for row in await cur.fetchall():
            out.setdefault(str(row["feature"]), []).append(int(row["channel_id"]))
        # Fall back to legacy columns when a feature has no guild_channels rows yet.
        for feature in FEATURE_SETTINGS_COLUMN:
            if not out.get(feature):
                out[feature] = await self.get_feature_channels(guild_id, feature)
        if not out.get("alts"):
            out["alts"] = await self.get_feature_channels(guild_id, "alts")
        return out

    async def set_feature_channel(self, guild_id: int, feature: str, channel_id: int | None) -> None:
        """Replace the channel(s) for a feature. None clears it. Also mirrors legacy columns."""
        await self.db.execute(
            "DELETE FROM guild_channels WHERE guild_id = ? AND feature = ?",
            (guild_id, feature),
        )
        if channel_id is not None:
            await self.db.execute(
                "INSERT INTO guild_channels (guild_id, feature, channel_id) VALUES (?, ?, ?)",
                (guild_id, feature, channel_id),
            )
        await self.db.commit()
        if feature in FEATURE_SETTINGS_COLUMN:
            await self.update_settings(guild_id, **{FEATURE_SETTINGS_COLUMN[feature]: channel_id})
        if feature == "alts":
            await self._upsert_alt_config(guild_id, log_channel_id=channel_id)

    async def add_feature_channel(self, guild_id: int, feature: str, channel_id: int) -> bool:
        """Add a channel for a multi-channel feature. Returns False if it was already set."""
        cur = await self.db.execute(
            "SELECT 1 FROM guild_channels WHERE guild_id = ? AND feature = ? AND channel_id = ?",
            (guild_id, feature, channel_id),
        )
        if await cur.fetchone():
            return False
        await self.db.execute(
            "INSERT INTO guild_channels (guild_id, feature, channel_id) VALUES (?, ?, ?)",
            (guild_id, feature, channel_id),
        )
        await self.db.commit()
        return True

    async def remove_feature_channel(self, guild_id: int, feature: str, channel_id: int | None = None) -> bool:
        """Remove one channel, or all channels for the feature if channel_id is None."""
        if channel_id is None:
            cur = await self.db.execute(
                "DELETE FROM guild_channels WHERE guild_id = ? AND feature = ?",
                (guild_id, feature),
            )
        else:
            cur = await self.db.execute(
                "DELETE FROM guild_channels WHERE guild_id = ? AND feature = ? AND channel_id = ?",
                (guild_id, feature, channel_id),
            )
        await self.db.commit()
        removed = cur.rowcount > 0
        if feature in FEATURE_SETTINGS_COLUMN:
            remaining = await self.get_feature_channels(guild_id, feature, fallback=False)
            await self.update_settings(
                guild_id,
                **{FEATURE_SETTINGS_COLUMN[feature]: remaining[0] if remaining else None},
            )
        if feature == "alts":
            remaining = await self.get_feature_channels(guild_id, feature, fallback=False)
            await self._upsert_alt_config(
                guild_id,
                log_channel_id=remaining[0] if remaining else None,
            )
        return removed

    # --- alt detection ---

    async def _upsert_alt_config(self, guild_id: int, **fields) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO alt_config (guild_id) VALUES (?)", (guild_id,)
        )
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [guild_id]
            await self.db.execute(f"UPDATE alt_config SET {cols} WHERE guild_id = ?", values)
        await self.db.commit()

    async def get_alt_config(self, guild_id: int) -> aiosqlite.Row:
        await self.db.execute(
            "INSERT OR IGNORE INTO alt_config (guild_id) VALUES (?)", (guild_id,)
        )
        await self.db.commit()
        cur = await self.db.execute("SELECT * FROM alt_config WHERE guild_id = ?", (guild_id,))
        row = await cur.fetchone()
        assert row is not None
        return row

    async def set_alt_config(self, guild_id: int, **fields) -> aiosqlite.Row:
        await self._upsert_alt_config(guild_id, **fields)
        if "log_channel_id" in fields:
            # Keep guild_channels in sync without looping back through set_feature_channel.
            await self.db.execute(
                "DELETE FROM guild_channels WHERE guild_id = ? AND feature = 'alts'",
                (guild_id,),
            )
            if fields["log_channel_id"] is not None:
                await self.db.execute(
                    "INSERT INTO guild_channels (guild_id, feature, channel_id) VALUES (?, 'alts', ?)",
                    (guild_id, fields["log_channel_id"]),
                )
            await self.db.commit()
        return await self.get_alt_config(guild_id)

    async def is_alt_whitelisted(self, guild_id: int, user_id: int) -> bool:
        cur = await self.db.execute(
            "SELECT 1 FROM alt_whitelist WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return await cur.fetchone() is not None

    async def add_alt_whitelist(self, guild_id: int, user_id: int, moderator_id: int) -> bool:
        import time
        try:
            await self.db.execute(
                "INSERT INTO alt_whitelist (guild_id, user_id, moderator_id, created_at) VALUES (?, ?, ?, ?)",
                (guild_id, user_id, moderator_id, time.time()),
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def remove_alt_whitelist(self, guild_id: int, user_id: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM alt_whitelist WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def add_alt_flag(
        self,
        guild_id: int,
        user_id: int,
        score: int,
        verdict: str,
        reasons: str,
        *,
        username: str | None = None,
        display_name: str | None = None,
        avatar_url: str | None = None,
        account_created_at: float | None = None,
        joined_at: float | None = None,
        action_taken: str | None = None,
        status: str | None = None,
    ) -> int:
        import time
        cur = await self.db.execute(
            """
            INSERT INTO alt_flags (
                guild_id, user_id, score, verdict, reasons, created_at,
                username, display_name, avatar_url, account_created_at, joined_at,
                action_taken, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id, user_id, score, verdict, reasons, time.time(),
                username, display_name, avatar_url, account_created_at, joined_at,
                action_taken, status,
            ),
        )
        await self.db.commit()
        return int(cur.lastrowid or 0)

    async def get_alt_flag(self, flag_id: int, guild_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM alt_flags WHERE id = ? AND guild_id = ?",
            (flag_id, guild_id),
        )
        return await cur.fetchone()

    async def update_alt_flag_action(
        self,
        *,
        flag_id: int | None = None,
        guild_id: int,
        user_id: int | None = None,
        action_taken: str,
        action_by: int | None = None,
        status: str | None = None,
    ) -> None:
        import time
        if flag_id is not None:
            await self.db.execute(
                """
                UPDATE alt_flags
                SET action_taken = ?, action_by = ?, action_at = ?, status = COALESCE(?, status)
                WHERE id = ? AND guild_id = ?
                """,
                (action_taken, action_by, time.time(), status, flag_id, guild_id),
            )
        elif user_id is not None:
            await self.db.execute(
                """
                UPDATE alt_flags
                SET action_taken = ?, action_by = ?, action_at = ?, status = COALESCE(?, status)
                WHERE id = (
                    SELECT id FROM alt_flags
                    WHERE guild_id = ? AND user_id = ?
                    ORDER BY created_at DESC LIMIT 1
                )
                """,
                (action_taken, action_by, time.time(), status, guild_id, user_id),
            )
        await self.db.commit()

    async def recent_alt_flags(self, guild_id: int, limit: int = 15) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM alt_flags WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cur.fetchall()

    async def search_alt_flags(
        self,
        guild_id: int,
        *,
        verdict: str | None = None,
        query: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[aiosqlite.Row], int]:
        where = ["guild_id = ?"]
        args: list = [guild_id]
        if verdict:
            where.append("verdict = ?")
            args.append(verdict)
        if query:
            q = f"%{query.strip()}%"
            where.append(
                "(CAST(user_id AS TEXT) LIKE ? OR IFNULL(username,'') LIKE ? "
                "OR IFNULL(display_name,'') LIKE ? OR IFNULL(reasons,'') LIKE ?)"
            )
            args.extend([q, q, q, q])
        clause = " AND ".join(where)
        cur = await self.db.execute(f"SELECT COUNT(*) AS n FROM alt_flags WHERE {clause}", args)
        row = await cur.fetchone()
        total = int(row["n"] if row else 0)
        cur = await self.db.execute(
            f"SELECT * FROM alt_flags WHERE {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            args + [limit, offset],
        )
        return await cur.fetchall(), total

    async def add_alt_mod_action(
        self,
        guild_id: int,
        user_id: int,
        action: str,
        account_created_at: float | None,
    ) -> None:
        import time
        await self.db.execute(
            "INSERT INTO alt_mod_actions (guild_id, user_id, action, account_created_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, action, account_created_at, time.time()),
        )
        await self.db.commit()

    async def recent_banned_account_creations(
        self, guild_id: int, since: float, exclude_user_id: int
    ) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            """
            SELECT DISTINCT user_id, account_created_at
            FROM alt_mod_actions
            WHERE guild_id = ?
              AND action = 'ban'
              AND created_at >= ?
              AND user_id != ?
              AND account_created_at IS NOT NULL
            """,
            (guild_id, since, exclude_user_id),
        )
        return await cur.fetchall()

    async def prior_alt_mod_actions(self, guild_id: int, user_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT action, created_at FROM alt_mod_actions WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC",
            (guild_id, user_id),
        )
        return await cur.fetchall()


    async def recent_warnings_guild(self, guild_id: int, limit: int = 40) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM warnings WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cur.fetchall()

    async def list_alt_whitelist(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM alt_whitelist WHERE guild_id = ? ORDER BY created_at DESC",
            (guild_id,),
        )
        return await cur.fetchall()

    async def add_mod_log(
        self,
        guild_id: int,
        action: str,
        detail: str | None = None,
        *,
        user_id: int | None = None,
        moderator_id: int | None = None,
    ) -> None:
        import time
        await self.db.execute(
            "INSERT INTO mod_log (guild_id, action, user_id, moderator_id, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, action, user_id, moderator_id, detail, time.time()),
        )
        await self.db.commit()

    async def recent_mod_log(self, guild_id: int, limit: int = 40) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM mod_log WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cur.fetchall()

    async def disabled_game_keys(self, guild_id: int) -> set[str]:
        cur = await self.db.execute(
            "SELECT game_key FROM disabled_games WHERE guild_id = ?",
            (guild_id,),
        )
        return {str(row["game_key"]) for row in await cur.fetchall()}

    async def is_game_enabled(self, guild_id: int, game_key: str) -> bool:
        cur = await self.db.execute(
            "SELECT 1 FROM disabled_games WHERE guild_id = ? AND game_key = ?",
            (guild_id, game_key),
        )
        return await cur.fetchone() is None

    async def set_game_enabled(self, guild_id: int, game_key: str, enabled: bool) -> None:
        if enabled:
            await self.db.execute(
                "DELETE FROM disabled_games WHERE guild_id = ? AND game_key = ?",
                (guild_id, game_key),
            )
        else:
            await self.db.execute(
                "INSERT OR IGNORE INTO disabled_games (guild_id, game_key) VALUES (?, ?)",
                (guild_id, game_key),
            )
        await self.db.commit()

    async def set_feature_channels(self, guild_id: int, feature: str, channel_ids: list[int]) -> None:
        """Replace the full channel list for a feature (used for multi-channel games)."""
        await self.db.execute(
            "DELETE FROM guild_channels WHERE guild_id = ? AND feature = ?",
            (guild_id, feature),
        )
        for channel_id in channel_ids:
            await self.db.execute(
                "INSERT OR IGNORE INTO guild_channels (guild_id, feature, channel_id) VALUES (?, ?, ?)",
                (guild_id, feature, channel_id),
            )
        await self.db.commit()


    # --- premium / subscriptions ---

    async def upsert_subscription(
        self,
        *,
        guild_id: int,
        payer_user_id: int | None = None,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        plan: str | None = None,
        status: str,
        current_period_end: float | None = None,
    ) -> None:
        import time
        now = time.time()
        existing = None
        if stripe_subscription_id:
            existing = await self.get_subscription_by_stripe_id(stripe_subscription_id)
        if existing is None and stripe_customer_id:
            cur = await self.db.execute(
                """
                SELECT * FROM subscriptions
                WHERE guild_id = ? AND stripe_customer_id = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (guild_id, stripe_customer_id),
            )
            existing = await cur.fetchone()
        if existing is None:
            await self.db.execute(
                """
                INSERT INTO subscriptions (
                    guild_id, payer_user_id, stripe_customer_id, stripe_subscription_id,
                    plan, status, current_period_end, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    payer_user_id,
                    stripe_customer_id,
                    stripe_subscription_id,
                    plan,
                    status,
                    current_period_end,
                    now,
                    now,
                ),
            )
        else:
            await self.db.execute(
                """
                UPDATE subscriptions SET
                    guild_id = ?,
                    payer_user_id = COALESCE(?, payer_user_id),
                    stripe_customer_id = COALESCE(?, stripe_customer_id),
                    stripe_subscription_id = COALESCE(?, stripe_subscription_id),
                    plan = COALESCE(?, plan),
                    status = ?,
                    current_period_end = COALESCE(?, current_period_end),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    guild_id,
                    payer_user_id,
                    stripe_customer_id,
                    stripe_subscription_id,
                    plan,
                    status,
                    current_period_end,
                    now,
                    int(existing["id"]),
                ),
            )
        await self.db.commit()

    async def get_subscription_by_stripe_id(self, stripe_subscription_id: str) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM subscriptions WHERE stripe_subscription_id = ?",
            (stripe_subscription_id,),
        )
        return await cur.fetchone()

    async def get_subscription_for_guild(self, guild_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            """
            SELECT * FROM subscriptions
            WHERE guild_id = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (guild_id,),
        )
        return await cur.fetchone()

    async def list_subscriptions(self) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM subscriptions ORDER BY updated_at DESC, id DESC"
        )
        return await cur.fetchall()

    async def add_premium_grant(
        self,
        *,
        grant_type: str,
        guild_id: int | None = None,
        user_id: int | None = None,
        expires_at: float | None = None,
        note: str | None = None,
        granted_by: int | None = None,
    ) -> int:
        import time
        cur = await self.db.execute(
            """
            INSERT INTO premium_grants (
                grant_type, guild_id, user_id, expires_at, note, granted_by, created_at, revoked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (grant_type, guild_id, user_id, expires_at, note, granted_by, time.time()),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def revoke_premium_grant(self, grant_id: int) -> bool:
        import time
        cur = await self.db.execute(
            "UPDATE premium_grants SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (time.time(), grant_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def revoke_guild_grants(self, guild_id: int) -> int:
        import time
        cur = await self.db.execute(
            """
            UPDATE premium_grants
            SET revoked_at = ?
            WHERE grant_type = 'guild' AND guild_id = ? AND revoked_at IS NULL
            """,
            (time.time(), guild_id),
        )
        await self.db.commit()
        return cur.rowcount

    async def get_premium_grant(self, grant_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute("SELECT * FROM premium_grants WHERE id = ?", (grant_id,))
        return await cur.fetchone()

    async def list_premium_grants(self, *, active_only: bool = False) -> list[aiosqlite.Row]:
        import time
        if active_only:
            now = time.time()
            cur = await self.db.execute(
                """
                SELECT * FROM premium_grants
                WHERE revoked_at IS NULL AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY created_at DESC, id DESC
                """,
                (now,),
            )
        else:
            cur = await self.db.execute(
                "SELECT * FROM premium_grants ORDER BY created_at DESC, id DESC"
            )
        return await cur.fetchall()

    async def list_active_guild_grants(self, guild_id: int, *, now: float | None = None) -> list[aiosqlite.Row]:
        import time
        if now is None:
            now = time.time()
        cur = await self.db.execute(
            """
            SELECT * FROM premium_grants
            WHERE grant_type = 'guild' AND guild_id = ? AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY created_at DESC
            """,
            (guild_id, now),
        )
        return await cur.fetchall()

    async def list_active_user_grants(self, user_id: int, *, now: float | None = None) -> list[aiosqlite.Row]:
        import time
        if now is None:
            now = time.time()
        cur = await self.db.execute(
            """
            SELECT * FROM premium_grants
            WHERE grant_type = 'user' AND user_id = ? AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY created_at DESC
            """,
            (user_id, now),
        )
        return await cur.fetchall()

    async def has_initial_guild_grant(self, guild_id: int) -> bool:
        cur = await self.db.execute(
            """
            SELECT 1 FROM premium_grants
            WHERE grant_type = 'guild' AND guild_id = ? AND note = 'initial' AND revoked_at IS NULL
            LIMIT 1
            """,
            (guild_id,),
        )
        return await cur.fetchone() is not None

    async def get_site_page(self, key: str) -> str | None:
        cur = await self.db.execute("SELECT body FROM site_pages WHERE key = ?", (key,))
        row = await cur.fetchone()
        return None if row is None else str(row["body"])

    async def set_site_page(self, key: str, body: str) -> None:
        import time
        await self.db.execute(
            """
            INSERT INTO site_pages (key, body, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at
            """,
            (key, body, time.time()),
        )
        await self.db.commit()



    async def _migrate_custom_roles_columns(self) -> None:
        cur = await self.db.execute("PRAGMA table_info(custom_roles)")
        cols = {str(row[1]) for row in await cur.fetchall()}
        if not cols:
            return
        if "secondary_colour" not in cols:
            await self.db.execute("ALTER TABLE custom_roles ADD COLUMN secondary_colour INTEGER")
        if "holder_id" not in cols:
            await self.db.execute("ALTER TABLE custom_roles ADD COLUMN holder_id INTEGER")
        await self.db.execute(
            "UPDATE custom_roles SET holder_id = user_id WHERE holder_id IS NULL"
        )
        cur = await self.db.execute("PRAGMA table_info(customrole_settings)")
        settings_cols = {str(row[1]) for row in await cur.fetchall()}
        if settings_cols and "give_enabled" not in settings_cols:
            await self.db.execute(
                "ALTER TABLE customrole_settings ADD COLUMN give_enabled INTEGER NOT NULL DEFAULT 1"
            )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_role_give_blocks (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                reason TEXT,
                by INTEGER,
                at REAL NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS profile_hidden_roles (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id, role_id)
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_role_perms (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                min_level INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_role_perm_list (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                permission TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, permission)
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_role_global_settings (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                min_level INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_role_global_perms (
                guild_id INTEGER NOT NULL,
                permission TEXT NOT NULL,
                PRIMARY KEY (guild_id, permission)
            )
            """
        )
        await self.db.commit()

    # --- custom roles ---

    async def get_customrole_settings(self, guild_id: int) -> aiosqlite.Row:
        await self.db.execute(
            "INSERT OR IGNORE INTO customrole_settings (guild_id) VALUES (?)",
            (guild_id,),
        )
        await self.db.commit()
        cur = await self.db.execute(
            "SELECT * FROM customrole_settings WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        return row

    async def set_customrole_settings(self, guild_id: int, **fields) -> aiosqlite.Row:
        await self.get_customrole_settings(guild_id)
        if fields:
            allowed = {"enabled", "min_level", "anchor_role_id", "give_enabled"}
            unknown = set(fields) - allowed
            if unknown:
                raise ValueError(f"Unknown custom role settings: {unknown}")
            cols = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [guild_id]
            await self.db.execute(
                f"UPDATE customrole_settings SET {cols} WHERE guild_id = ?",
                values,
            )
            await self.db.commit()
        return await self.get_customrole_settings(guild_id)

    async def get_custom_role(self, guild_id: int, user_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM custom_roles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return await cur.fetchone()

    async def get_custom_role_by_role_id(self, guild_id: int, role_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM custom_roles WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id),
        )
        return await cur.fetchone()

    async def list_custom_roles(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM custom_roles WHERE guild_id = ? ORDER BY created_at DESC",
            (guild_id,),
        )
        return await cur.fetchall()

    async def add_custom_role(
        self, guild_id: int, user_id: int, role_id: int, *, secondary_colour: int | None = None
    ) -> None:
        import time
        await self.db.execute(
            """
            INSERT INTO custom_roles (guild_id, user_id, role_id, created_at, secondary_colour, holder_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (guild_id, user_id, role_id, time.time(), secondary_colour, user_id),
        )
        await self.db.commit()

    async def set_custom_role_secondary(self, guild_id: int, user_id: int, secondary_colour: int | None) -> None:
        await self.db.execute(
            "UPDATE custom_roles SET secondary_colour = ? WHERE guild_id = ? AND user_id = ?",
            (secondary_colour, guild_id, user_id),
        )
        await self.db.commit()

    async def get_custom_role_held(self, guild_id: int, user_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM custom_roles WHERE guild_id = ? AND COALESCE(holder_id, user_id) = ?",
            (guild_id, user_id),
        )
        return await cur.fetchone()

    async def set_custom_role_holder(self, guild_id: int, owner_id: int, holder_id: int) -> None:
        await self.db.execute(
            "UPDATE custom_roles SET holder_id = ? WHERE guild_id = ? AND user_id = ?",
            (holder_id, guild_id, owner_id),
        )
        await self.db.commit()


    async def delete_custom_role(self, guild_id: int, user_id: int) -> aiosqlite.Row | None:
        row = await self.get_custom_role(guild_id, user_id)
        if row is None:
            return None
        await self.db.execute(
            "DELETE FROM custom_roles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self.db.commit()
        return row

    async def delete_custom_role_by_role_id(self, guild_id: int, role_id: int) -> aiosqlite.Row | None:
        row = await self.get_custom_role_by_role_id(guild_id, role_id)
        if row is None:
            return None
        await self.db.execute(
            "DELETE FROM custom_roles WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id),
        )
        await self.db.commit()
        return row

    async def is_custom_role_restricted(self, guild_id: int, user_id: int) -> bool:
        cur = await self.db.execute(
            "SELECT 1 FROM custom_role_restrictions WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return await cur.fetchone() is not None

    async def get_custom_role_restriction(self, guild_id: int, user_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM custom_role_restrictions WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return await cur.fetchone()

    async def restrict_custom_role_user(
        self, guild_id: int, user_id: int, *, reason: str | None, by: int | None
    ) -> None:
        import time
        await self.db.execute(
            """
            INSERT INTO custom_role_restrictions (guild_id, user_id, reason, by, at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                reason = excluded.reason,
                by = excluded.by,
                at = excluded.at
            """,
            (guild_id, user_id, reason, by, time.time()),
        )
        await self.db.commit()

    async def unrestrict_custom_role_user(self, guild_id: int, user_id: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM custom_role_restrictions WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def list_custom_role_restrictions(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM custom_role_restrictions WHERE guild_id = ? ORDER BY at DESC",
            (guild_id,),
        )
        return await cur.fetchall()

    async def get_profile_hidden_roles(self, guild_id: int, user_id: int) -> list[int]:
        cur = await self.db.execute(
            "SELECT role_id FROM profile_hidden_roles WHERE guild_id = ? AND user_id = ?",
            (int(guild_id), int(user_id)),
        )
        return [int(row["role_id"]) for row in await cur.fetchall()]

    async def set_profile_hidden_roles(self, guild_id: int, user_id: int, role_ids: list[int]) -> None:
        await self.db.execute(
            "DELETE FROM profile_hidden_roles WHERE guild_id = ? AND user_id = ?",
            (int(guild_id), int(user_id)),
        )
        for role_id in {int(rid) for rid in role_ids}:
            await self.db.execute(
                "INSERT OR IGNORE INTO profile_hidden_roles (guild_id, user_id, role_id) VALUES (?, ?, ?)",
                (int(guild_id), int(user_id), int(role_id)),
            )
        await self.db.commit()

    async def is_custom_role_give_blocked(self, guild_id: int, user_id: int) -> bool:
        cur = await self.db.execute(
            "SELECT 1 FROM custom_role_give_blocks WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return await cur.fetchone() is not None

    async def block_custom_role_give(self, guild_id: int, user_id: int, *, reason: str | None, by: int | None) -> None:
        import time
        await self.db.execute(
            """
            INSERT INTO custom_role_give_blocks (guild_id, user_id, reason, by, at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET reason = excluded.reason, by = excluded.by, at = excluded.at
            """,
            (guild_id, user_id, reason, by, time.time()),
        )
        await self.db.commit()

    async def unblock_custom_role_give(self, guild_id: int, user_id: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM custom_role_give_blocks WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def list_custom_role_give_blocks(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM custom_role_give_blocks WHERE guild_id = ? ORDER BY at DESC",
            (guild_id,),
        )
        return await cur.fetchall()

    # --- custom role permissions (per owner, not server roles) ---

    async def get_custom_role_perms(self, guild_id: int, user_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM custom_role_perms WHERE guild_id = ? AND user_id = ?",
            (int(guild_id), int(user_id)),
        )
        return await cur.fetchone()

    async def set_custom_role_perms(
        self, guild_id: int, user_id: int, *, enabled: int | None = None, min_level: int | None = None
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO custom_role_perms (guild_id, user_id, enabled, min_level)
            VALUES (?, ?, 1, 0)
            ON CONFLICT(guild_id, user_id) DO NOTHING
            """,
            (int(guild_id), int(user_id)),
        )
        fields = []
        values: list = []
        if enabled is not None:
            fields.append("enabled = ?")
            values.append(int(enabled))
        if min_level is not None:
            fields.append("min_level = ?")
            values.append(int(min_level))
        if fields:
            values.extend([int(guild_id), int(user_id)])
            await self.db.execute(
                f"UPDATE custom_role_perms SET {', '.join(fields)} WHERE guild_id = ? AND user_id = ?",
                values,
            )
        await self.db.commit()

    async def get_custom_role_permissions(self, guild_id: int, user_id: int) -> list[str]:
        cur = await self.db.execute(
            "SELECT permission FROM custom_role_perm_list WHERE guild_id = ? AND user_id = ? ORDER BY permission",
            (int(guild_id), int(user_id)),
        )
        return [str(row["permission"]) for row in await cur.fetchall()]

    async def set_custom_role_permission(
        self, guild_id: int, user_id: int, permission: str, enabled: bool
    ) -> None:
        if enabled:
            await self.db.execute(
                """
                INSERT OR IGNORE INTO custom_role_perm_list (guild_id, user_id, permission)
                VALUES (?, ?, ?)
                """,
                (int(guild_id), int(user_id), permission),
            )
        else:
            await self.db.execute(
                "DELETE FROM custom_role_perm_list WHERE guild_id = ? AND user_id = ? AND permission = ?",
                (int(guild_id), int(user_id), permission),
            )
        await self.db.commit()

    async def clear_custom_role_permissions(self, guild_id: int, user_id: int) -> None:
        await self.db.execute(
            "DELETE FROM custom_role_perm_list WHERE guild_id = ? AND user_id = ?",
            (int(guild_id), int(user_id)),
        )
        await self.db.commit()

    async def has_custom_role_permission(self, guild_id: int, user_id: int, permission: str) -> bool:
        cur = await self.db.execute(
            "SELECT 1 FROM custom_role_perm_list WHERE guild_id = ? AND user_id = ? AND permission = ?",
            (int(guild_id), int(user_id), permission),
        )
        return await cur.fetchone() is not None

    async def list_custom_role_perms_rows(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM custom_role_perms WHERE guild_id = ? ORDER BY user_id",
            (int(guild_id),),
        )
        return await cur.fetchall()

    # --- custom role global config (single panel, not per-owner) ---

    async def get_custom_role_global_settings(self, guild_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM custom_role_global_settings WHERE guild_id = ?",
            (int(guild_id),),
        )
        return await cur.fetchone()

    async def set_custom_role_global_settings(
        self, guild_id: int, *, enabled: int | None = None, min_level: int | None = None
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO custom_role_global_settings (guild_id, enabled, min_level)
            VALUES (?, 1, 0)
            ON CONFLICT(guild_id) DO NOTHING
            """,
            (int(guild_id),),
        )
        fields = []
        values: list = []
        if enabled is not None:
            fields.append("enabled = ?")
            values.append(int(enabled))
        if min_level is not None:
            fields.append("min_level = ?")
            values.append(int(min_level))
        if fields:
            values.append(int(guild_id))
            await self.db.execute(
                f"UPDATE custom_role_global_settings SET {', '.join(fields)} WHERE guild_id = ?",
                values,
            )
        await self.db.commit()

    async def get_custom_role_global_permissions(self, guild_id: int) -> list[str]:
        cur = await self.db.execute(
            "SELECT permission FROM custom_role_global_perms WHERE guild_id = ? ORDER BY permission",
            (int(guild_id),),
        )
        return [str(row["permission"]) for row in await cur.fetchall()]

    async def set_custom_role_global_permission(
        self, guild_id: int, permission: str, enabled: bool
    ) -> None:
        if enabled:
            await self.db.execute(
                """
                INSERT OR IGNORE INTO custom_role_global_perms (guild_id, permission)
                VALUES (?, ?)
                """,
                (int(guild_id), permission),
            )
        else:
            await self.db.execute(
                "DELETE FROM custom_role_global_perms WHERE guild_id = ? AND permission = ?",
                (int(guild_id), permission),
            )
        await self.db.commit()

    async def has_custom_role_global_permission(self, guild_id: int, permission: str) -> bool:
        cur = await self.db.execute(
            "SELECT 1 FROM custom_role_global_perms WHERE guild_id = ? AND permission = ?",
            (int(guild_id), permission),
        )
        return await cur.fetchone() is not None

    async def clear_custom_role_global_permissions(self, guild_id: int) -> None:
        await self.db.execute(
            "DELETE FROM custom_role_global_perms WHERE guild_id = ?",
            (int(guild_id),),
        )
        await self.db.commit()

    async def alt_flag_created_times(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            """
            SELECT user_id, MAX(account_created_at) AS account_created_at
            FROM alt_flags
            WHERE guild_id = ?
            GROUP BY user_id
            """,
            (guild_id,),
        )
        return await cur.fetchall()

    async def has_alt_flag(self, guild_id: int, user_id: int) -> bool:
        cur = await self.db.execute(
            "SELECT 1 FROM alt_flags WHERE guild_id = ? AND user_id = ? LIMIT 1",
            (guild_id, user_id),
        )
        return await cur.fetchone() is not None



    async def _migrate_report_columns(self) -> None:
        cur = await self.db.execute("PRAGMA table_info(report_settings)")
        settings_cols = {str(row[1]) for row in await cur.fetchall()}
        if settings_cols and "closed_channel_id" not in settings_cols:
            await self.db.execute("ALTER TABLE report_settings ADD COLUMN closed_channel_id INTEGER")
        cur = await self.db.execute("PRAGMA table_info(report_tickets)")
        cols = {str(row[1]) for row in await cur.fetchall()}
        if cols:
            additions = {
                "announce_channel_id": "INTEGER",
                "announce_message_id": "INTEGER",
                "reporter_name": "TEXT",
                "reporter_avatar": "TEXT",
                "reported_name": "TEXT",
                "reported_avatar": "TEXT",
                "claimed_by_name": "TEXT",
                "claimed_by_avatar": "TEXT",
                "decided_by_name": "TEXT",
                "decided_by_avatar": "TEXT",
                "closed_by_name": "TEXT",
                "closed_by_avatar": "TEXT",
                "reporter_dm_channel_id": "INTEGER",
                "reporter_dm_message_id": "INTEGER",
            }
            for name, typ in additions.items():
                if name not in cols:
                    await self.db.execute(f"ALTER TABLE report_tickets ADD COLUMN {name} {typ}")
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS report_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                author_id INTEGER,
                author_name TEXT,
                author_avatar TEXT,
                body TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_report_notes_ticket ON report_notes(ticket_id, created_at)"
        )

    async def _migrate_fun_slaps_columns(self) -> None:
        cur = await self.db.execute("PRAGMA table_info(fun_slaps)")
        cols = {str(row[1]) for row in await cur.fetchall()}
        if cols and "action" not in cols:
            await self.db.execute("ALTER TABLE fun_slaps ADD COLUMN action TEXT DEFAULT 'slap'")

    # --- reports ---

    async def get_report_settings(self, guild_id: int) -> aiosqlite.Row:
        await self.db.execute(
            "INSERT OR IGNORE INTO report_settings (guild_id) VALUES (?)",
            (guild_id,),
        )
        await self.db.commit()
        cur = await self.db.execute("SELECT * FROM report_settings WHERE guild_id = ?", (guild_id,))
        row = await cur.fetchone()
        assert row is not None
        return row

    async def set_report_settings(self, guild_id: int, **fields) -> aiosqlite.Row:
        await self.get_report_settings(guild_id)
        if fields:
            allowed = {"enabled", "mode", "category_id", "alert_channel_id", "closed_channel_id", "staff_role_id"}
            unknown = set(fields) - allowed
            if unknown:
                raise ValueError(f"Unknown report settings: {unknown}")
            if "mode" in fields and fields["mode"] not in {"channel", "ticket"}:
                raise ValueError("mode must be channel or ticket")
            cols = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [guild_id]
            await self.db.execute(f"UPDATE report_settings SET {cols} WHERE guild_id = ?", values)
            await self.db.commit()
        return await self.get_report_settings(guild_id)

    async def create_report_ticket(
        self,
        guild_id: int,
        *,
        reporter_id: int,
        reporter_name: str | None = None,
        reporter_avatar: str | None = None,
        reported_user_id: int | None,
        reported_name: str | None = None,
        reported_avatar: str | None = None,
        message_link: str | None,
        message_preview: str | None,
        reason: str | None,
        channel_id: int | None = None,
        message_channel_id: int | None = None,
        message_id: int | None = None,
    ) -> int:
        import time
        cur = await self.db.execute(
            """
            INSERT INTO report_tickets (
                guild_id, channel_id, message_channel_id, message_id,
                reporter_id, reporter_name, reporter_avatar,
                reported_user_id, reported_name, reported_avatar,
                message_link, message_preview, reason, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
            """,
            (
                guild_id, channel_id, message_channel_id, message_id,
                reporter_id, reporter_name, reporter_avatar,
                reported_user_id, reported_name, reported_avatar,
                message_link, message_preview, reason, time.time(),
            ),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def set_report_panel(
        self,
        ticket_id: int,
        *,
        channel_id: int | None,
        message_channel_id: int,
        message_id: int,
        announce_channel_id: int | None = None,
        announce_message_id: int | None = None,
    ) -> None:
        await self.db.execute(
            """
            UPDATE report_tickets
            SET channel_id = ?, message_channel_id = ?, message_id = ?,
                announce_channel_id = ?, announce_message_id = ?
            WHERE id = ?
            """,
            (channel_id, message_channel_id, message_id, announce_channel_id, announce_message_id, ticket_id),
        )
        await self.db.commit()

    async def set_report_dm_message(self, ticket_id: int, channel_id: int, message_id: int) -> None:
        await self.db.execute(
            """
            UPDATE report_tickets
            SET reporter_dm_channel_id = ?, reporter_dm_message_id = ?
            WHERE id = ?
            """,
            (int(channel_id), int(message_id), int(ticket_id)),
        )
        await self.db.commit()

    async def get_report_ticket(self, ticket_id: int, guild_id: int | None = None) -> aiosqlite.Row | None:
        if guild_id is None:
            cur = await self.db.execute("SELECT * FROM report_tickets WHERE id = ?", (ticket_id,))
        else:
            cur = await self.db.execute(
                "SELECT * FROM report_tickets WHERE id = ? AND guild_id = ?",
                (ticket_id, guild_id),
            )
        return await cur.fetchone()

    async def list_report_tickets(
        self, guild_id: int, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[aiosqlite.Row]:
        if status:
            cur = await self.db.execute(
                """
                SELECT * FROM report_tickets
                WHERE guild_id = ? AND status = ?
                ORDER BY created_at DESC LIMIT ? OFFSET ?
                """,
                (guild_id, status, limit, offset),
            )
        else:
            cur = await self.db.execute(
                "SELECT * FROM report_tickets WHERE guild_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (guild_id, limit, offset),
            )
        return await cur.fetchall()

    async def count_reports(self, guild_id: int, status: str | None = None) -> int:
        if status:
            cur = await self.db.execute(
                "SELECT COUNT(*) AS n FROM report_tickets WHERE guild_id = ? AND status = ?",
                (guild_id, status),
            )
        else:
            cur = await self.db.execute(
                "SELECT COUNT(*) AS n FROM report_tickets WHERE guild_id = ?",
                (guild_id,),
            )
        row = await cur.fetchone()
        return int(row["n"] if row else 0)

    async def count_open_reports(self, guild_id: int, reporter_id: int) -> int:
        cur = await self.db.execute(
            """
            SELECT COUNT(*) AS n FROM report_tickets
            WHERE guild_id = ? AND reporter_id = ? AND status = 'open'
            """,
            (guild_id, reporter_id),
        )
        row = await cur.fetchone()
        return int(row["n"] if row else 0)

    async def last_report_at(self, guild_id: int, reporter_id: int) -> float | None:
        cur = await self.db.execute(
            """
            SELECT MAX(created_at) AS ts FROM report_tickets
            WHERE guild_id = ? AND reporter_id = ?
            """,
            (guild_id, reporter_id),
        )
        row = await cur.fetchone()
        if row is None or row["ts"] is None:
            return None
        return float(row["ts"])

    async def claim_report_ticket(
        self, ticket_id: int, user_id: int, *, name: str | None = None, avatar: str | None = None
    ) -> None:
        import time
        await self.db.execute(
            """
            UPDATE report_tickets
            SET claimed_by = ?, claimed_by_name = ?, claimed_by_avatar = ?, claimed_at = ?
            WHERE id = ?
            """,
            (user_id, name, avatar, time.time(), ticket_id),
        )
        await self.db.commit()

    async def decide_report_ticket(
        self,
        ticket_id: int,
        *,
        status: str,
        decided_by: int,
        decided_by_name: str | None = None,
        decided_by_avatar: str | None = None,
        decision_reason: str | None,
    ) -> None:
        import time
        await self.db.execute(
            """
            UPDATE report_tickets
            SET status = ?, decided_by = ?, decided_by_name = ?, decided_by_avatar = ?,
                decided_at = ?, decision_reason = ?
            WHERE id = ?
            """,
            (status, decided_by, decided_by_name, decided_by_avatar, time.time(), decision_reason, ticket_id),
        )
        await self.db.commit()

    async def close_report_ticket(
        self, ticket_id: int, *, closed_by: int | None, closed_by_name: str | None = None, closed_by_avatar: str | None = None
    ) -> None:
        import time
        await self.db.execute(
            """
            UPDATE report_tickets
            SET status = CASE WHEN status = 'open' THEN 'closed' ELSE status END,
                closed_at = ?, closed_by = ?, closed_by_name = ?, closed_by_avatar = ?
            WHERE id = ?
            """,
            (time.time(), closed_by, closed_by_name, closed_by_avatar, ticket_id),
        )
        await self.db.commit()

    async def delete_report_ticket(self, ticket_id: int, guild_id: int) -> bool:
        await self.db.execute(
            "DELETE FROM report_notes WHERE ticket_id = ? AND guild_id = ?",
            (ticket_id, guild_id),
        )
        cur = await self.db.execute(
            "DELETE FROM report_tickets WHERE id = ? AND guild_id = ?",
            (ticket_id, guild_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def add_report_note(
        self,
        ticket_id: int,
        guild_id: int,
        *,
        author_id: int | None,
        author_name: str | None,
        author_avatar: str | None,
        body: str,
    ) -> int:
        import time
        cur = await self.db.execute(
            """
            INSERT INTO report_notes (
                ticket_id, guild_id, author_id, author_name, author_avatar, body, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ticket_id, guild_id, author_id, author_name, author_avatar, body, time.time()),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def list_report_notes(self, ticket_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM report_notes WHERE ticket_id = ? ORDER BY created_at ASC",
            (ticket_id,),
        )
        return await cur.fetchall()

    async def list_report_notes_for(self, ticket_ids: list[int]) -> dict[int, list[aiosqlite.Row]]:
        out: dict[int, list[aiosqlite.Row]] = {int(i): [] for i in ticket_ids}
        if not ticket_ids:
            return out
        placeholders = ",".join("?" * len(ticket_ids))
        cur = await self.db.execute(
            f"SELECT * FROM report_notes WHERE ticket_id IN ({placeholders}) ORDER BY created_at ASC",
            list(ticket_ids),
        )
        for row in await cur.fetchall():
            out[int(row["ticket_id"])].append(row)
        return out

    async def is_report_blocked(self, guild_id: int, user_id: int) -> bool:
        cur = await self.db.execute(
            "SELECT 1 FROM report_blocks WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return await cur.fetchone() is not None

    async def block_reporter(self, guild_id: int, user_id: int, *, reason: str | None, by: int | None) -> None:
        import time
        await self.db.execute(
            """
            INSERT INTO report_blocks (guild_id, user_id, reason, by, at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                reason = excluded.reason, by = excluded.by, at = excluded.at
            """,
            (guild_id, user_id, reason, by, time.time()),
        )
        await self.db.commit()

    async def unblock_reporter(self, guild_id: int, user_id: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM report_blocks WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def list_report_blocks(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM report_blocks WHERE guild_id = ? ORDER BY at DESC",
            (guild_id,),
        )
        return await cur.fetchall()

    # --- YouTube settings ---

    async def get_youtube_settings(self, guild_id: int) -> aiosqlite.Row:
        await self.db.execute(
            "INSERT OR IGNORE INTO youtube_settings (guild_id) VALUES (?)",
            (guild_id,),
        )
        await self.db.commit()
        cur = await self.db.execute(
            "SELECT * FROM youtube_settings WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        return row

    async def set_youtube_settings(self, guild_id: int, **fields) -> aiosqlite.Row:
        await self.get_youtube_settings(guild_id)
        if fields:
            allowed = {"enabled", "channel_id"}
            unknown = set(fields) - allowed
            if unknown:
                raise ValueError(f"Unknown youtube settings: {unknown}")
            cols = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [guild_id]
            await self.db.execute(
                f"UPDATE youtube_settings SET {cols} WHERE guild_id = ?",
                values,
            )
            await self.db.commit()
        return await self.get_youtube_settings(guild_id)

    async def is_youtube_enabled(self, guild_id: int) -> bool:
        row = await self.get_youtube_settings(guild_id)
        return int(row["enabled"] or 0) == 1

    # --- YouTube schedule ---

    async def add_youtube_schedule(
        self, guild_id: int, channel_id: int, video_url: str, scheduled_at: float
    ) -> int:
        import time
        cur = await self.db.execute(
            """
            INSERT INTO youtube_schedule (guild_id, channel_id, video_url, scheduled_at, posted)
            VALUES (?, ?, ?, ?, 0)
            """,
            (guild_id, channel_id, video_url, scheduled_at),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def list_youtube_schedule(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM youtube_schedule WHERE guild_id = ? AND posted = 0 ORDER BY scheduled_at ASC",
            (guild_id,),
        )
        return await cur.fetchall()

    async def mark_youtube_posted(self, schedule_id: int) -> None:
        import time
        await self.db.execute(
            "UPDATE youtube_schedule SET posted = 1, posted_at = ? WHERE id = ?",
            (time.time(), schedule_id),
        )
        await self.db.commit()

    async def delete_youtube_schedule(self, schedule_id: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM youtube_schedule WHERE id = ?",
            (schedule_id,),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # --- YouTube OAuth tokens ---

    async def save_youtube_token(
        self, user_id: int, guild_id: int | None, access_token: str,
        refresh_token: str | None, expires_at: float
    ) -> None:
        await self.db.execute(
            """
            INSERT OR REPLACE INTO youtube_tokens (user_id, guild_id, access_token, refresh_token, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, guild_id, access_token, refresh_token, expires_at, time.time()),
        )
        await self.db.commit()

    async def get_youtube_token(self, user_id: int, guild_id: int | None) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM youtube_tokens WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )
        return await cur.fetchone()

    async def delete_youtube_token(self, user_id: int, guild_id: int | None) -> bool:
        cur = await self.db.execute(
            "DELETE FROM youtube_tokens WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # --- fun slaps ---

    async def add_fun_slap(self, guild_id: int, slapper_id: int, slapped_id: int, action: str = "slap") -> int:
        import time
        cur = await self.db.execute(
            """
            INSERT INTO fun_slaps (guild_id, slapper_id, slapped_id, action, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guild_id, slapper_id, slapped_id, action, time.time()),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def count_fun_slaps(self, guild_id: int, slapped_id: int, action: str = "slap") -> int:
        cur = await self.db.execute(
            "SELECT COUNT(*) as n FROM fun_slaps WHERE guild_id = ? AND slapped_id = ? AND action = ?",
            (guild_id, slapped_id, action),
        )
        row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def list_recent_slaps(self, guild_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM fun_slaps WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cur.fetchall()
