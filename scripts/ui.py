import re

import discord

from . import config, db, utils, leaderboard_db
from .db import GuildConfig

CHANNEL_REF_RE = re.compile(r"#([\w\-]+)")
ROLE_REF_RE = re.compile(r"@([\w\-]+)")

COLOUR = discord.Colour.dark_gold()

COOLDOWN_VALIDATION_MSG = (
    f"Invalid cooldown. Enter **{config.MIN_COOLDOWN_MINS}–{config.MAX_COOLDOWN_MINS} "
    f"minutes** (e.g. `60`)."
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _resolve_channel_refs(text: str, guild: discord.Guild) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1).lower()
        channel = discord.utils.find(lambda c: c.name.lower() == name, guild.channels)
        return f"<#{channel.id}>" if channel else match.group(0)

    return CHANNEL_REF_RE.sub(replace, text)


def _resolve_role_refs(text: str, guild: discord.Guild) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1).lower()
        role = discord.utils.find(
            lambda r: r.name.lower() == name and not r.is_default(), guild.roles
        )
        return f"<@&{role.id}>" if role else match.group(0)

    return ROLE_REF_RE.sub(replace, text)


def _parse_cooldown(raw: str) -> int | None:
    try:
        minutes = int(raw.strip())
    except ValueError:
        return None
    if config.MIN_COOLDOWN_MINS <= minutes <= config.MAX_COOLDOWN_MINS:
        return minutes * 60
    return None


def _format_cooldown_input(secs: int) -> str:
    return str(secs // 60)


def _button(
    label: str, custom_id: str, callback, emoji: str | None = None
) -> discord.ui.Button:
    btn = discord.ui.Button(
        label=label,
        emoji=emoji,
        style=discord.ButtonStyle.secondary,
        custom_id=custom_id,
    )
    btn.callback = callback
    return btn


def _link_buttons() -> list[discord.ui.Button]:
    links = [
        ("Invite", config.INVITE_URL, None),
        ("Website", config.WEBSITE_URL, None),
        ("Patreon", config.PATREON_URL, "💖"),
    ]
    return [
        discord.ui.Button(
            label=label, url=url, emoji=emoji, style=discord.ButtonStyle.link
        )
        for label, url, emoji in links
        if url
    ]


async def _deny_non_admin(interaction: discord.Interaction) -> bool:
    """Returns True and replies if the user lacks Manage Server."""
    perms = getattr(interaction.user, "guild_permissions", None)
    if perms and perms.manage_guild:
        return False
    await interaction.response.send_message(
        "You need **Manage Server** to change this.", ephemeral=True
    )
    return True


def _perks_summary(cfg: GuildConfig) -> str:
    count = len(cfg.perks)
    return f"{count} set" if count else "none"


def _entries_text(rows: list[tuple[int, int]]) -> str:
    """One line per leaderboard entry; medals for the top 3."""
    if not rows:
        return "Nobody has awakened the chat yet."
    lines = []
    for index, (user_id, count) in enumerate(rows):
        prefix = ("🥇", "🥈", "🥉")[index] if index < 3 else "•"
        lines.append(
            f"{prefix} <@{user_id}> — {count} awakening{'s' if count != 1 else ''}"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Public claim / status message
# --------------------------------------------------------------------------- #


class AwakenerStatusView(discord.ui.LayoutView):
    def __init__(self, text: str = "### The Awakener") -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Container(
                discord.ui.Section(
                    discord.ui.TextDisplay(text),
                    accessory=_button("Read More...", "awakener:info", self.show_info),
                ),
                accent_colour=COLOUR,
            )
        )

    async def show_info(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
            cfg = utils.get_config(interaction.guild_id)
            top_rows = await leaderboard_db.top(utils.lb_conn, interaction.guild_id, 3)
            await interaction.followup.send(
                view=InfoView(cfg, top_rows), ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
        except (discord.NotFound, discord.HTTPException):
            pass


# --------------------------------------------------------------------------- #
# Leaderboard (public card)
# --------------------------------------------------------------------------- #


class LeaderboardView(discord.ui.LayoutView):
    def __init__(self, rows: list[tuple[int, int]]) -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("### Top Awakeners"),
                discord.ui.TextDisplay(_entries_text(rows)),
                discord.ui.TextDisplay("-# /leaderboard"),
                accent_colour=COLOUR,
            )
        )


# --------------------------------------------------------------------------- #
# Info panel (ephemeral)
# --------------------------------------------------------------------------- #


class InfoView(discord.ui.LayoutView):
    def __init__(self, cfg: GuildConfig, top_rows: list[tuple[int, int]]) -> None:
        super().__init__(timeout=None)

        cooldown = config.format_cooldown(cfg.cooldown_secs)
        channel = f"<#{cfg.channel_id}>" if cfg.channel_id else "the configured channel"
        role_line = f"- Earn the <@&{cfg.role_id}> role.\n" if cfg.role_id else ""
        perks = (
            "\n".join(f"- {perk}" for perk in cfg.perks)
            if cfg.perks
            else config.DEFAULT_PERKS_MESSAGE
        )

        items: list[discord.ui.Item] = [
            discord.ui.TextDisplay("### How to play"),
            discord.ui.TextDisplay(
                f"If {channel} stays quiet for **{cooldown}**, the first person to "
                "revive it gains the role.\n"
                "If the chat goes quiet again, you lose it. "
                "Only one person can hold the role at a time."
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay("**Top Awakeners**"),
            discord.ui.TextDisplay(_entries_text(top_rows)),
            discord.ui.ActionRow(
                _button("More", "info:leaderboard", self.show_leaderboard)
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay(f"**Perks:**\n{role_line}{perks}"),
        ]

        links = _link_buttons()
        if links:
            items.append(discord.ui.ActionRow(*links))

        items.append(discord.ui.TextDisplay("-# /awaken • /leaderboard • /config"))

        self.add_item(discord.ui.Container(*items, accent_colour=COLOUR))

    async def show_leaderboard(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
            rows = await leaderboard_db.top(utils.lb_conn, interaction.guild_id, 10)
            await interaction.followup.send(
                view=LeaderboardView(rows),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.NotFound, discord.HTTPException):
            pass


# --------------------------------------------------------------------------- #
# /config panel
# --------------------------------------------------------------------------- #


class ConfigView(discord.ui.LayoutView):
    def __init__(self, cfg: GuildConfig) -> None:
        super().__init__(timeout=None)

        channel = f"<#{cfg.channel_id}>" if cfg.channel_id else "*not set*"
        role = f"<@&{cfg.role_id}>" if cfg.role_id else "*not set*"

        self.channel_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text],
            placeholder="Pick a channel",
            custom_id="config:channel",
        )
        self.channel_select.callback = self.on_channel

        self.role_select = discord.ui.RoleSelect(
            placeholder="Pick a role",
            custom_id="config:role",
        )
        self.role_select.callback = self.on_role

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("## Awakener Settings"),
                discord.ui.Separator(),
                discord.ui.TextDisplay(f"**Channel**\n{channel}"),
                discord.ui.ActionRow(self.channel_select),
                discord.ui.TextDisplay(
                    "-# 🛈 The only channel where chat activity is tracked."
                ),
                discord.ui.TextDisplay(f"**Role**\n{role}"),
                discord.ui.ActionRow(self.role_select),
                discord.ui.TextDisplay(
                    "-# 🛈 The role given to whoever revives the chat."
                ),
                discord.ui.Separator(),
                discord.ui.Section(
                    discord.ui.TextDisplay(
                        f"**Cooldown**\n{config.format_cooldown(cfg.cooldown_secs)}"
                    ),
                    accessory=_button(
                        "Edit", "config:cooldown", self.on_cooldown, "⏱️"
                    ),
                ),
                discord.ui.TextDisplay(
                    "-# 🛈 How long the chat must stay silent before it counts as dead."
                ),
                discord.ui.Section(
                    discord.ui.TextDisplay(f"**Perks**\n{_perks_summary(cfg)}"),
                    accessory=_button("Edit", "config:perks", self.on_perks, "📝"),
                ),
                discord.ui.TextDisplay(
                    "-# 🛈 The perks shown to whoever holds the role."
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    "**Leaderboard**\nMaintenance for awakening counts."
                ),
                discord.ui.ActionRow(
                    _button("Purge", "config:purge", self.on_purge, "🧹"),
                    _button("Reset", "config:reset", self.on_reset, "⚠️"),
                ),
                discord.ui.TextDisplay(
                    "-# - Purge removes entries for members no longer in the server.\n"
                    "-# - Reset wipes all awakening counts for this server."
                ),
                accent_colour=COLOUR,
            )
        )

    async def on_channel(self, interaction: discord.Interaction) -> None:
        if await _deny_non_admin(interaction):
            return

        cfg = utils.get_config(interaction.guild_id)
        selected = self.channel_select.values[0]

        if cfg.channel_id != selected.id:
            cfg.channel_id = selected.id
            await db.save_config(utils.db_conn, cfg)
            state = utils.get_state(cfg.guild_id)
            state.last_message_ts = None
            await db.save_state(utils.db_conn, state)

        await interaction.response.edit_message(view=ConfigView(cfg))

    async def on_role(self, interaction: discord.Interaction) -> None:
        if await _deny_non_admin(interaction):
            return

        cfg = utils.get_config(interaction.guild_id)
        cfg.role_id = self.role_select.values[0].id
        await db.save_config(utils.db_conn, cfg)
        await interaction.response.edit_message(view=ConfigView(cfg))

    async def on_cooldown(self, interaction: discord.Interaction) -> None:
        if await _deny_non_admin(interaction):
            return

        cfg = utils.get_config(interaction.guild_id)
        await interaction.response.send_modal(CooldownModal(cfg.cooldown_secs))

    async def on_perks(self, interaction: discord.Interaction) -> None:
        if await _deny_non_admin(interaction):
            return

        cfg = utils.get_config(interaction.guild_id)
        await interaction.response.send_modal(PerksModal(cfg.perks_text))

    async def on_purge(self, interaction: discord.Interaction) -> None:
        if await _deny_non_admin(interaction):
            return

        await interaction.response.send_message(view=PurgeConfirmView(), ephemeral=True)

    async def on_reset(self, interaction: discord.Interaction) -> None:
        if await _deny_non_admin(interaction):
            return

        await interaction.response.send_message(view=ResetConfirmView(), ephemeral=True)


class PurgeConfirmView(discord.ui.LayoutView):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        confirm = _button("Confirm", "purge:confirm", self.do_purge)
        confirm.style = discord.ButtonStyle.success
        cancel = _button("Cancel", "purge:cancel", self.cancel)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "This will remove leaderboard entries for members no longer "
                    "in the server. Continue?"
                ),
                discord.ui.ActionRow(confirm, cancel),
                accent_colour=COLOUR,
            )
        )

    async def do_purge(self, interaction: discord.Interaction) -> None:
        if await _deny_non_admin(interaction):
            return

        present = [member.id for member in interaction.guild.members]
        rows = await leaderboard_db.all_rows(utils.lb_conn, interaction.guild_id)
        await leaderboard_db.purge_missing(utils.lb_conn, interaction.guild_id, present)
        removed = sum(1 for user_id in rows if user_id not in present)
        await interaction.response.edit_message(view=PurgeResultView(removed))

    async def cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=CancelledResultView())


class ResetConfirmView(discord.ui.LayoutView):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        confirm = _button("Confirm", "reset:confirm", self.do_reset)
        confirm.style = discord.ButtonStyle.success
        cancel = _button("Cancel", "reset:cancel", self.cancel)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "This will wipe all awakening counts for this server. Continue?"
                ),
                discord.ui.ActionRow(confirm, cancel),
                accent_colour=COLOUR,
            )
        )

    async def do_reset(self, interaction: discord.Interaction) -> None:
        if await _deny_non_admin(interaction):
            return

        await leaderboard_db.reset_guild(utils.lb_conn, interaction.guild_id)
        await interaction.response.edit_message(view=ResetResultView())

    async def cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=CancelledResultView())


class PurgeResultView(discord.ui.LayoutView):
    def __init__(self, removed: int) -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(f"✅ Purged {removed} gone member entries."),
                accent_colour=COLOUR,
            )
        )


class ResetResultView(discord.ui.LayoutView):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("✅ Leaderboard reset."),
                accent_colour=COLOUR,
            )
        )


class CancelledResultView(discord.ui.LayoutView):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("Cancelled."),
                accent_colour=COLOUR,
            )
        )


class CooldownModal(discord.ui.Modal, title="Cooldown"):
    cooldown = discord.ui.TextInput(
        label=f"Minutes ({config.MIN_COOLDOWN_MINS}–{config.MAX_COOLDOWN_MINS})",
        placeholder=f"{config.MIN_COOLDOWN_MINS}  •  60  •  {config.MAX_COOLDOWN_MINS}",
        max_length=5,
    )

    def __init__(self, current_secs: int = config.DEFAULT_COOLDOWN_SECS) -> None:
        super().__init__()
        self.cooldown.default = _format_cooldown_input(current_secs)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if await _deny_non_admin(interaction):
            return

        secs = _parse_cooldown(str(self.cooldown))
        if secs is None:
            await interaction.response.send_message(
                COOLDOWN_VALIDATION_MSG, ephemeral=True
            )
            return

        cfg = utils.get_config(interaction.guild_id)
        cfg.cooldown_secs = secs
        await db.save_config(utils.db_conn, cfg)
        await interaction.response.edit_message(view=ConfigView(cfg))


class PerksModal(discord.ui.Modal, title="Perks"):
    perks = discord.ui.TextInput(
        label="One perk per line",
        style=discord.TextStyle.paragraph,
        placeholder="Priority in #general\nAccess to @Awakener",
        max_length=config.PERKS_MAX_LENGTH,
        required=False,
    )

    def __init__(self, current_perks: str = "") -> None:
        super().__init__()
        self.perks.default = current_perks or None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if await _deny_non_admin(interaction):
            return

        cfg = utils.get_config(interaction.guild_id)
        raw = str(self.perks)

        if interaction.guild:
            raw = _resolve_channel_refs(raw, interaction.guild)
            raw = _resolve_role_refs(raw, interaction.guild)

        cfg.perks_text = "\n".join(
            line.strip() for line in raw.splitlines() if line.strip()
        )
        await db.save_config(utils.db_conn, cfg)
        await interaction.response.edit_message(view=ConfigView(cfg))
