"""Awakener — a multi-server Discord bot backed by SQLite.

The bot watches a configured channel per guild. Once the channel has been
silent for the configured cooldown, the next human message claims the
Awakener role from the previous holder.
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import aiosqlite
import discord
from discord import app_commands

DB_PATH = Path(os.getenv("DB_PATH", "awakener.db"))

MIN_COOLDOWN_MINS = 5
MAX_COOLDOWN_MINS = 360  # 6 hours
DEFAULT_COOLDOWN_MINS = 60

DEFAULT_PERKS_MESSAGE = "No perks have been configured by the admins yet."
PERKS_MAX_LENGTH = 1800

log = logging.getLogger("awakener")


def load_env_file(path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE pairs from .env without extra dependencies."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_env_file()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
INVITE_URL = os.getenv("INVITE_URL", "").strip()
PATREON_URL = os.getenv("PATREON_URL", "").strip()

_sync_guild = os.getenv("GUILD_ID", "").strip()
GUILD_ID = int(_sync_guild) if _sync_guild.isdigit() else None


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id      INTEGER PRIMARY KEY,
    channel_id    INTEGER,
    role_id       INTEGER,
    cooldown_mins INTEGER NOT NULL DEFAULT 60,
    perks_text    TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS guild_state (
    guild_id          INTEGER PRIMARY KEY,
    last_message_ts   TEXT,
    current_holder_id INTEGER
);
"""


@dataclass
class GuildConfig:
    guild_id: int
    channel_id: int | None = None
    role_id: int | None = None
    cooldown_mins: int = DEFAULT_COOLDOWN_MINS
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


async def open_db(path: Path) -> aiosqlite.Connection:
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.executescript(SCHEMA)
    await db.commit()
    return db


def _row_to_config(row: aiosqlite.Row) -> GuildConfig:
    return GuildConfig(
        guild_id=row["guild_id"],
        channel_id=row["channel_id"],
        role_id=row["role_id"],
        cooldown_mins=row["cooldown_mins"],
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


async def save_config(db: aiosqlite.Connection, config: GuildConfig) -> None:
    await db.execute(
        """
        INSERT INTO guild_config
            (guild_id, channel_id, role_id, cooldown_mins, perks_text)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            channel_id    = excluded.channel_id,
            role_id       = excluded.role_id,
            cooldown_mins = excluded.cooldown_mins,
            perks_text    = excluded.perks_text
        """,
        (
            config.guild_id,
            config.channel_id,
            config.role_id,
            config.cooldown_mins,
            config.perks_text,
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


# --------------------------------------------------------------------------- #
# Resolution helpers
# --------------------------------------------------------------------------- #


def _strip_mention(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<#") or value.startswith("<@") or value.startswith("<@&"):
        value = value[2:]
    value = value.lstrip("&!#").rstrip(">")
    return value.strip()


def resolve_channel(guild: discord.Guild, raw: str) -> discord.TextChannel | None:
    value = _strip_mention(raw)
    if value.isdigit():
        channel = guild.get_channel(int(value))
        return channel if isinstance(channel, discord.TextChannel) else None
    needle = value.lstrip("#").lower()
    for channel in guild.text_channels:
        if channel.name.lower() == needle:
            return channel
    return None


def resolve_role(guild: discord.Guild, raw: str) -> discord.Role | None:
    value = _strip_mention(raw)
    if value.isdigit():
        return guild.get_role(int(value))
    needle = value.lower()
    for role in guild.roles:
        if role.name.lower() == needle:
            return role
    return None


def role_problem(guild: discord.Guild, role: discord.Role) -> str | None:
    """Return a human-readable reason the bot cannot hand out this role."""
    if role.is_default():
        return "The @everyone role can't be used."
    if role.managed:
        return "That role is managed by an integration and can't be assigned manually."
    me = guild.me
    if me is not None and role >= me.top_role:
        return (
            "That role is above (or equal to) the bot's highest role. "
            "Move the bot's role higher in Server Settings → Roles."
        )
    return None


def admin_denied(interaction: discord.Interaction) -> bool:
    """True when the interaction must not proceed with config changes."""
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return True
    return not interaction.user.guild_permissions.manage_guild


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #


class AwakenerStatusView(discord.ui.View):
    """Public, persistent view attached to status/claim messages."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        if INVITE_URL:
            self.add_item(
                discord.ui.Button(
                    label="Invite",
                    style=discord.ButtonStyle.link,
                    url=INVITE_URL,
                    emoji="📨",
                    row=1,
                )
            )
        if PATREON_URL:
            self.add_item(
                discord.ui.Button(
                    label="Patreon",
                    style=discord.ButtonStyle.link,
                    url=PATREON_URL,
                    emoji="💖",
                    row=1,
                )
            )

    def _config(self, interaction: discord.Interaction) -> GuildConfig | None:
        bot: AwakenerBot = interaction.client  # type: ignore[assignment]
        return bot.configs.get(interaction.guild_id or 0)

    @discord.ui.button(
        label="Info",
        style=discord.ButtonStyle.secondary,
        emoji="ℹ️",
        custom_id="awakener:info",
    )
    async def show_info(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        config = self._config(interaction)
        cooldown = config.cooldown_mins if config else DEFAULT_COOLDOWN_MINS
        channel = f"<#{config.channel_id}>" if config and config.channel_id else "not set"
        role = f"<@&{config.role_id}>" if config and config.role_id else "not set"

        embed = discord.Embed(
            title="🔥 The Awakener Role — How It Works",
            description=(
                "Revive a silent chat and claim the Awakener role.\n\n"
                "**Timer**\n"
                f"The channel must stay silent for **{cooldown} minutes** before a "
                "message can claim the role.\n\n"
                "**How it works**\n"
                "The first person to speak after the silence claims the role. The "
                "previous holder loses it. Sending another message yourself while you "
                "hold the role does not re-claim it.\n\n"
                f"**Channel:** {channel}\n**Role:** {role}"
            ),
            colour=discord.Colour.gold(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Perks",
        style=discord.ButtonStyle.secondary,
        emoji="🎁",
        custom_id="awakener:perks",
    )
    async def show_perks(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        config = self._config(interaction)
        perks = config.perks if config else []
        description = (
            "\n".join(f"• {perk}" for perk in perks)
            if perks
            else DEFAULT_PERKS_MESSAGE
        )
        embed = discord.Embed(
            title="🔥 Awakener Perks",
            description=description,
            colour=discord.Colour.gold(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Setup",
        style=discord.ButtonStyle.danger,
        emoji="⚙️",
        custom_id="awakener:setup",
    )
    async def open_setup(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if admin_denied(interaction):
            await interaction.response.send_message(
                "You need the **Manage Server** permission to configure the bot.",
                ephemeral=True,
            )
            return

        bot: AwakenerBot = interaction.client  # type: ignore[assignment]
        config = bot.configs.get(interaction.guild_id or 0)
        embed = build_setup_embed(interaction.guild, config)
        await interaction.response.send_message(
            embed=embed, view=AwakenerSetupView(), ephemeral=True
        )


class AwakenerSetupView(discord.ui.View):
    """Admin-only ephemeral panel with modal launchers."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if admin_denied(interaction):
            await interaction.response.send_message(
                "You need the **Manage Server** permission to configure the bot.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Set Channel",
        style=discord.ButtonStyle.primary,
        emoji="📺",
        custom_id="awakener:set_channel",
    )
    async def set_channel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if await self._guard(interaction):
            await interaction.response.send_modal(ChannelModal())

    @discord.ui.button(
        label="Set Role",
        style=discord.ButtonStyle.primary,
        emoji="🎭",
        custom_id="awakener:set_role",
    )
    async def set_role(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if await self._guard(interaction):
            await interaction.response.send_modal(RoleModal())

    @discord.ui.button(
        label="Set Cooldown",
        style=discord.ButtonStyle.primary,
        emoji="⏱️",
        custom_id="awakener:set_cooldown",
    )
    async def set_cooldown(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if await self._guard(interaction):
            await interaction.response.send_modal(CooldownModal())

    @discord.ui.button(
        label="Edit Perks",
        style=discord.ButtonStyle.primary,
        emoji="📝",
        custom_id="awakener:edit_perks",
    )
    async def edit_perks(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._guard(interaction):
            return
        bot: AwakenerBot = interaction.client  # type: ignore[assignment]
        config = bot.configs.get(interaction.guild_id or 0)
        await interaction.response.send_modal(
            PerksModal(config.perks_text if config else "")
        )


def build_setup_embed(
    guild: discord.Guild | None, config: GuildConfig | None
) -> discord.Embed:
    embed = discord.Embed(
        title="⚙️ Awakener Setup",
        description=(
            "Configure how the Awakener role is claimed on this server.\n"
            f"Cooldown range: **{MIN_COOLDOWN_MINS}–{MAX_COOLDOWN_MINS} minutes**."
        ),
        colour=discord.Colour.gold(),
    )
    if guild is None:
        return embed

    if config is None:
        embed.add_field(name="Channel", value="not set", inline=True)
        embed.add_field(name="Role", value="not set", inline=True)
        embed.add_field(name="Cooldown", value="not set", inline=True)
        embed.add_field(name="Perks", value="none", inline=False)
        return embed

    channel = guild.get_channel(config.channel_id) if config.channel_id else None
    role = guild.get_role(config.role_id) if config.role_id else None
    embed.add_field(
        name="Channel",
        value=channel.mention if channel else "not set / deleted",
        inline=True,
    )
    embed.add_field(
        name="Role",
        value=role.mention if role else "not set / deleted",
        inline=True,
    )
    embed.add_field(
        name="Cooldown", value=f"{config.cooldown_mins} minutes", inline=True
    )
    perks = config.perks
    embed.add_field(
        name="Perks",
        value=f"{len(perks)} configured" if perks else "none",
        inline=False,
    )
    return embed


# --------------------------------------------------------------------------- #
# Modals
# --------------------------------------------------------------------------- #


class ChannelModal(discord.ui.Modal, title="Set Awakener Channel"):
    channel = discord.ui.TextInput(
        label="Channel ID, #mention, or name",
        placeholder="#general  •  1387002318247034900  •  general",
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if admin_denied(interaction) or interaction.guild is None:
            await interaction.response.send_message(
                "You need the **Manage Server** permission to configure the bot.",
                ephemeral=True,
            )
            return

        resolved = resolve_channel(interaction.guild, str(self.channel))
        if resolved is None:
            await interaction.response.send_message(
                "Couldn't find that text channel on this server. Try the channel "
                "ID, a #mention, or the exact channel name.",
                ephemeral=True,
            )
            return

        bot: AwakenerBot = interaction.client  # type: ignore[assignment]
        config = bot.configs.get(interaction.guild.id) or GuildConfig(
            guild_id=interaction.guild.id
        )
        changed = config.channel_id != resolved.id
        config.channel_id = resolved.id
        await bot.persist_config(config)

        if changed:
            # A freshly selected channel starts with a fresh silence window.
            state = bot.states.get(interaction.guild.id) or GuildState(
                guild_id=interaction.guild.id
            )
            state.last_message_ts = None
            await bot.persist_state(state)

        await interaction.response.send_message(
            f"Awakener channel set to {resolved.mention}.", ephemeral=True
        )


class RoleModal(discord.ui.Modal, title="Set Awakener Role"):
    role = discord.ui.TextInput(
        label="Role ID, @mention, or name",
        placeholder="@Awakener  •  1106806475080335410  •  Awakener",
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if admin_denied(interaction) or interaction.guild is None:
            await interaction.response.send_message(
                "You need the **Manage Server** permission to configure the bot.",
                ephemeral=True,
            )
            return

        resolved = resolve_role(interaction.guild, str(self.role))
        if resolved is None:
            await interaction.response.send_message(
                "Couldn't find that role on this server. Try the role ID, an "
                "@mention, or the exact role name.",
                ephemeral=True,
            )
            return

        problem = role_problem(interaction.guild, resolved)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return

        bot: AwakenerBot = interaction.client  # type: ignore[assignment]
        config = bot.configs.get(interaction.guild.id) or GuildConfig(
            guild_id=interaction.guild.id
        )
        config.role_id = resolved.id
        await bot.persist_config(config)

        await interaction.response.send_message(
            f"Awakener role set to {resolved.mention}.", ephemeral=True
        )


class CooldownModal(discord.ui.Modal, title="Set Awakener Cooldown"):
    minutes = discord.ui.TextInput(
        label="Silence required before a claim (minutes)",
        placeholder=f"{MIN_COOLDOWN_MINS}–{MAX_COOLDOWN_MINS} (e.g. 60)",
        max_length=3,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if admin_denied(interaction) or interaction.guild is None:
            await interaction.response.send_message(
                "You need the **Manage Server** permission to configure the bot.",
                ephemeral=True,
            )
            return

        raw = str(self.minutes).strip()
        if not raw.isdigit():
            await interaction.response.send_message(
                "Cooldown must be a whole number of minutes.", ephemeral=True
            )
            return

        minutes = int(raw)
        if not MIN_COOLDOWN_MINS <= minutes <= MAX_COOLDOWN_MINS:
            await interaction.response.send_message(
                f"Cooldown must be between {MIN_COOLDOWN_MINS} and "
                f"{MAX_COOLDOWN_MINS} minutes.",
                ephemeral=True,
            )
            return

        bot: AwakenerBot = interaction.client  # type: ignore[assignment]
        config = bot.configs.get(interaction.guild.id) or GuildConfig(
            guild_id=interaction.guild.id
        )
        config.cooldown_mins = minutes
        await bot.persist_config(config)

        await interaction.response.send_message(
            f"Awakener cooldown set to **{minutes} minutes**.", ephemeral=True
        )


class PerksModal(discord.ui.Modal, title="Edit Awakener Perks"):
    perks = discord.ui.TextInput(
        label="One perk per line",
        style=discord.TextStyle.paragraph,
        placeholder="Priority in #general\nAccess to the lounge channel\n…",
        max_length=PERKS_MAX_LENGTH,
        required=False,
    )

    def __init__(self, current_perks: str = "") -> None:
        super().__init__()
        self.perks.default = current_perks or None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if admin_denied(interaction) or interaction.guild is None:
            await interaction.response.send_message(
                "You need the **Manage Server** permission to configure the bot.",
                ephemeral=True,
            )
            return

        lines = [line.strip() for line in str(self.perks).splitlines()]
        text = "\n".join(line for line in lines if line)

        bot: AwakenerBot = interaction.client  # type: ignore[assignment]
        config = bot.configs.get(interaction.guild.id) or GuildConfig(
            guild_id=interaction.guild.id
        )
        config.perks_text = text
        await bot.persist_config(config)

        count = len(config.perks)
        message = (
            f"Saved **{count} perk{'s' if count != 1 else ''}**."
            if count
            else "Perks cleared."
        )
        await interaction.response.send_message(message, ephemeral=True)


# --------------------------------------------------------------------------- #
# Slash command
# --------------------------------------------------------------------------- #


@app_commands.command(
    name="awakener", description="Show who currently holds the Awakener role"
)
async def awakener_command(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command only works inside a server.", ephemeral=True
        )
        return

    bot: AwakenerBot = interaction.client  # type: ignore[assignment]
    config = bot.configs.get(interaction.guild.id)
    state = bot.states.get(interaction.guild.id)

    embed = discord.Embed(title="🔥 Awakener Status", colour=discord.Colour.gold())

    if config is None or not config.channel_id or not config.role_id:
        embed.description = (
            "This server isn't configured yet.\n"
            "An admin can press **⚙️ Setup** below to pick the channel, role, "
            "cooldown, and perks."
        )
    else:
        holder = (
            f"<@{state.current_holder_id}>"
            if state and state.current_holder_id
            else "No one yet"
        )
        embed.add_field(name="Current Awakener", value=holder, inline=True)
        embed.add_field(
            name="Channel", value=f"<#{config.channel_id}>", inline=True
        )
        embed.add_field(name="Role", value=f"<@&{config.role_id}>", inline=True)
        embed.add_field(
            name="Cooldown", value=f"{config.cooldown_mins} minutes", inline=True
        )
        if state and state.last_message_ts:
            embed.add_field(
                name="Silence started",
                value=f"<t:{int(state.last_message_ts.timestamp())}:R>",
                inline=True,
            )
        else:
            embed.add_field(name="Silence started", value="Waiting for messages", inline=True)

    await interaction.response.send_message(
        embed=embed, view=AwakenerStatusView()
    )


# --------------------------------------------------------------------------- #
# Bot
# --------------------------------------------------------------------------- #


class AwakenerBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        # Privileged, but required for role hand-off (member lookup/cache).
        intents.members = True
        # message_content is intentionally NOT enabled: message text is never read.
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.db: aiosqlite.Connection | None = None
        self.configs: dict[int, GuildConfig] = {}
        self.states: dict[int, GuildState] = {}

    async def setup_hook(self) -> None:
        self.db = await open_db(DB_PATH)
        self.configs = await load_configs(self.db)
        self.states = await load_states(self.db)

        self.add_view(AwakenerStatusView())
        self.add_view(AwakenerSetupView())
        self.tree.add_command(awakener_command)

        try:
            if GUILD_ID is not None:
                guild = discord.Object(id=GUILD_ID)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
            else:
                synced = await self.tree.sync()
            log.info("Synced %d slash command(s).", len(synced))
        except discord.HTTPException:
            log.exception("Failed to sync slash commands.")

    async def close(self) -> None:
        if self.db is not None:
            await self.db.close()
            self.db = None
        await super().close()

    async def persist_config(self, config: GuildConfig) -> None:
        assert self.db is not None
        self.configs[config.guild_id] = config
        await save_config(self.db, config)

    async def persist_state(self, state: GuildState) -> None:
        assert self.db is not None
        self.states[state.guild_id] = state
        await save_state(self.db, state)

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id %s) — Awakener monitor active.", self.user, self.user and self.user.id)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.webhook_id is not None:
            return
        if message.guild is None:
            return

        config = self.configs.get(message.guild.id)
        if config is None or config.channel_id is None or config.role_id is None:
            return
        if message.channel.id != config.channel_id:
            return

        state = self.states.get(message.guild.id) or GuildState(
            guild_id=message.guild.id
        )
        now = discord.utils.utcnow()
        previous_ts = state.last_message_ts

        # Always remember "last human message" so the timer restarts.
        state.last_message_ts = now
        await self.persist_state(state)

        if previous_ts is None:
            return
        if (now - previous_ts).total_seconds() < config.cooldown_mins * 60:
            return
        if message.author.id == state.current_holder_id:
            return

        guild = message.guild
        role = guild.get_role(config.role_id)
        if role is None:
            log.warning("Guild %s: configured role is missing.", guild.id)
            return

        problem = role_problem(guild, role)
        if problem:
            log.warning("Guild %s: cannot assign role: %s", guild.id, problem)
            return

        previous_holder_id = state.current_holder_id
        if previous_holder_id and previous_holder_id != message.author.id:
            await self._remove_role_from_previous_holder(
                guild, previous_holder_id, role
            )

        try:
            await message.author.add_roles(role, reason="Revived a silent chat")
        except (discord.Forbidden, discord.HTTPException):
            log.exception("Guild %s: failed to assign the Awakener role.", guild.id)
            return

        state.current_holder_id = message.author.id
        await self.persist_state(state)

        embed = discord.Embed(
            title="🔥 The Awakener has risen!",
            description=(
                f"{message.author.mention} broke the silence and claimed "
                f"{role.mention}.\n\n"
                f"The channel must stay quiet for **{config.cooldown_mins} minutes** "
                "before someone else can take it."
            ),
            colour=discord.Colour.gold(),
        )
        try:
            await message.channel.send(
                embed=embed,
                view=AwakenerStatusView(),
                reference=message,
                mention_author=False,
                silent=True,
            )
        except discord.HTTPException:
            log.exception("Guild %s: failed to send the claim message.", guild.id)

    async def _remove_role_from_previous_holder(
        self, guild: discord.Guild, holder_id: int, role: discord.Role
    ) -> None:
        member = guild.get_member(holder_id)
        if member is None:
            try:
                member = await guild.fetch_member(holder_id)
            except (discord.NotFound, discord.HTTPException):
                member = None

        if member is None or role not in member.roles:
            return

        try:
            await member.remove_roles(role, reason="Chat awakened by someone else")
        except (discord.Forbidden, discord.HTTPException):
            log.exception(
                "Guild %s: failed to remove the role from the previous holder.",
                guild.id,
            )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not TOKEN:
        raise SystemExit(
            "DISCORD_TOKEN is not set. Add it to .env or the environment."
        )

    bot = AwakenerBot()
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
