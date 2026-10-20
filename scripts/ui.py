"""Components V2 panels, persistent views, and the /config panel."""

import discord

from . import config, db, utils
from .db import GuildConfig

COLOUR = discord.Colour.dark_gold()

COOLDOWN_VALIDATION_MSG = (
    f"Invalid cooldown. Enter **{config.MIN_COOLDOWN_MINS}–{config.MAX_COOLDOWN_MINS} minutes** "
    f"(e.g. `60`) or `10s`–`{config.MAX_COOLDOWN_SECS}s` for testing."
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _parse_cooldown(raw: str) -> int | None:
    raw = raw.strip().lower()
    try:
        if raw.endswith("s"):
            secs = int(raw[:-1])
            return secs if 5 <= secs <= config.MAX_COOLDOWN_SECS else None
        minutes = int(raw)
        if config.MIN_COOLDOWN_MINS <= minutes <= config.MAX_COOLDOWN_MINS:
            return minutes * 60
    except ValueError:
        pass
    return None


def _format_cooldown_input(secs: int) -> str:
    return str(secs // 60) if secs % 60 == 0 else f"{secs}s"


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
                    accessory=_button("Info", "awakener:info", self.show_info, "ℹ️"),
                ),
                accent_colour=COLOUR,
            )
        )

    async def show_info(self, interaction: discord.Interaction) -> None:
        cfg = utils.get_config(interaction.guild_id)
        await interaction.response.send_message(view=InfoView(cfg), ephemeral=True)


# --------------------------------------------------------------------------- #
# Info panel (ephemeral)
# --------------------------------------------------------------------------- #


class InfoView(discord.ui.LayoutView):
    def __init__(self, cfg: GuildConfig) -> None:
        super().__init__(timeout=None)

        cooldown = config.format_cooldown(cfg.cooldown_secs)
        perks = (
            "\n".join(f"• {perk}" for perk in cfg.perks)
            if cfg.perks
            else config.DEFAULT_PERKS_MESSAGE
        )

        items: list[discord.ui.Item] = [
            discord.ui.TextDisplay("### The Awakener"),
            discord.ui.TextDisplay(
                f"Silence for **{cooldown}** and the next message claims the role. "
                "The previous holder loses it."
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay("**Perks**"),
            discord.ui.TextDisplay(perks),
        ]

        links = _link_buttons()
        if links:
            items += [discord.ui.Separator(), discord.ui.ActionRow(*links)]

        items.append(discord.ui.TextDisplay("-# /awakener"))

        self.add_item(discord.ui.Container(*items, accent_colour=COLOUR))


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
                discord.ui.TextDisplay(f"**Role**\n{role}"),
                discord.ui.ActionRow(self.role_select),
                discord.ui.Separator(),
                discord.ui.Section(
                    discord.ui.TextDisplay(
                        f"**Cooldown**\n{config.format_cooldown(cfg.cooldown_secs)}"
                    ),
                    accessory=_button(
                        "Edit", "config:cooldown", self.on_cooldown, "⏱️"
                    ),
                ),
                discord.ui.Section(
                    discord.ui.TextDisplay(f"**Perks**\n{_perks_summary(cfg)}"),
                    accessory=_button("Edit", "config:perks", self.on_perks, "📝"),
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


class CooldownModal(discord.ui.Modal, title="Cooldown"):
    cooldown = discord.ui.TextInput(
        label=f"Minutes ({config.MIN_COOLDOWN_MINS}–{config.MAX_COOLDOWN_MINS}) or seconds",
        placeholder=f"60  •  10s for testing  •  {config.MAX_COOLDOWN_MINS}",
        max_length=10,
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
        placeholder="Priority in #general\nAccess to the lounge channel",
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
        cfg.perks_text = "\n".join(
            line.strip() for line in str(self.perks).splitlines() if line.strip()
        )
        await db.save_config(utils.db_conn, cfg)
        await interaction.response.edit_message(view=ConfigView(cfg))
