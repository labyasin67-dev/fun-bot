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
    jtc_category_id INTEGER
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

    async def clear_warnings(self, guild_id: int, user_id: int) -> int:
        cur = await self.db.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await self.db.commit()
        return cur.rowcount


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
