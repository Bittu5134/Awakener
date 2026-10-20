"""Components V2 panels, persistent views, and the /config panel."""

import discord

from . import config, db, utils
from .db import GuildConfig

COLOUR = discord.Colour.dark_gold()


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


class AwakenerStatusView(discord.ui.LayoutView):
    def __init__(self, text: str = "### The Awakener") -> None:
        super().__init__(timeout=None)
        btn = discord.ui.Button(label="Info", style=discord.ButtonStyle.secondary, custom_id="awakener:info")
        btn.callback = self.show_info
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(text),
                discord.ui.ActionRow(btn),
                accent_colour=COLOUR,
            )
        )

    async def show_info(self, interaction: discord.Interaction) -> None:
        cfg = utils.get_config(interaction.guild_id)
        await interaction.response.send_message(view=InfoView(cfg), ephemeral=True)


class InfoView(discord.ui.LayoutView):
    def __init__(self, cfg: GuildConfig | None = None) -> None:
        super().__init__(timeout=None)
        cooldown = config.format_cooldown(cfg.cooldown_secs) if cfg else "not set"
        channel = f"<#{cfg.channel_id}>" if cfg and cfg.channel_id else "not set"
        role = f"<@&{cfg.role_id}>" if cfg and cfg.role_id else "not set"
        perks = cfg.perks if cfg else []
        perks_body = "\n".join(f"• {p}" for p in perks) if perks else config.DEFAULT_PERKS_MESSAGE

        links = []
        if config.INVITE_URL:
            links.append(discord.ui.Button(label="Invite", style=discord.ButtonStyle.link, url=config.INVITE_URL))
        if config.WEBSITE_URL:
            links.append(discord.ui.Button(label="Website", style=discord.ButtonStyle.link, url=config.WEBSITE_URL))
        if config.PATREON_URL:
            links.append(discord.ui.Button(label="Patreon", emoji="💖", style=discord.ButtonStyle.link, url=config.PATREON_URL))

        items = [
            discord.ui.TextDisplay("### The Awakener"),
            discord.ui.TextDisplay(
                f"**Timer:** the channel must be silent for **{cooldown}** before a message claims the role.\n"
                "**Rules:** the person who revives the chat after silence becomes the Awakener, "
                "and the previous holder loses the role."
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay("### Role Perks"),
            discord.ui.TextDisplay(perks_body),
            discord.ui.Separator(),
            discord.ui.TextDisplay(f"-# {channel} · {role} · /awaken"),
        ]
        if links:
            items.append(discord.ui.ActionRow(*links))

        self.add_item(discord.ui.Container(*items, accent_colour=COLOUR))


class ConfigView(discord.ui.LayoutView):
    def __init__(self, cfg: GuildConfig) -> None:
        super().__init__(timeout=None)

        channel_display = f"<#{cfg.channel_id}>" if cfg.channel_id else "*None selected*"
        role_display = f"<@&{cfg.role_id}>" if cfg.role_id else "*None selected*"
        cooldown_display = config.format_cooldown(cfg.cooldown_secs)
        perks_display = f"{len(cfg.perks)} configured" if cfg.perks else "*None*"

        self.channel_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text],
            placeholder="Select channel...",
            custom_id="config:channel",
        )
        self.channel_select.callback = self.on_channel

        self.role_select = discord.ui.RoleSelect(
            placeholder="Select role...",
            custom_id="config:role",
        )
        self.role_select.callback = self.on_role

        cooldown_btn = discord.ui.Button(label=f"Cooldown ({cooldown_display})", emoji="⏱️", style=discord.ButtonStyle.secondary, custom_id="config:cooldown")
        cooldown_btn.callback = self.on_cooldown

        perks_btn = discord.ui.Button(label=f"Perks ({perks_display})", emoji="📝", style=discord.ButtonStyle.secondary, custom_id="config:perks")
        perks_btn.callback = self.on_perks

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("## Settings"),
                discord.ui.TextDisplay("Configure which channel to monitor, which role to grant, and chat revival timers."),
                discord.ui.Separator(),

                discord.ui.TextDisplay(f"**Channel** • Currently: {channel_display}"),
                discord.ui.ActionRow(self.channel_select),
                discord.ui.TextDisplay("-# 🛈 Chat activity will be tracked exclusively inside this channel."),

                discord.ui.TextDisplay(f"**Awakener Role** • Currently: {role_display}"),
                discord.ui.ActionRow(self.role_select),
                discord.ui.TextDisplay("-# 🛈 Select the role that should be awarded to the user."),

                discord.ui.TextDisplay("**Timer & Perks**"),
                discord.ui.ActionRow(cooldown_btn, perks_btn),
                discord.ui.TextDisplay("-# 🛈 How long to wait before chat is considered dead."),
                discord.ui.TextDisplay("-# 🛈 Edit the perks to show to the users."),

                accent_colour=COLOUR,
            )
        )

    async def on_channel(self, interaction: discord.Interaction) -> None:
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
        cfg = utils.get_config(interaction.guild_id)
        cfg.role_id = self.role_select.values[0].id
        await db.save_config(utils.db_conn, cfg)
        await interaction.response.edit_message(view=ConfigView(cfg))

    async def on_cooldown(self, interaction: discord.Interaction) -> None:
        cfg = utils.get_config(interaction.guild_id)
        await interaction.response.send_modal(CooldownModal(cfg.cooldown_secs))

    async def on_perks(self, interaction: discord.Interaction) -> None:
        cfg = utils.get_config(interaction.guild_id)
        await interaction.response.send_modal(PerksModal(cfg.perks_text))


class CooldownModal(discord.ui.Modal, title="Set Awakener Cooldown"):
    cooldown = discord.ui.TextInput(
        label="Cooldown duration",
        placeholder="60 (minutes) or 10s (seconds)",
        max_length=10,
    )

    def __init__(self, current_secs: int = config.DEFAULT_COOLDOWN_SECS) -> None:
        super().__init__()
        self.cooldown.default = _format_cooldown_input(current_secs)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        secs = _parse_cooldown(str(self.cooldown))
        if secs is None:
            await interaction.response.send_message(
                f"Enter 5–{config.MAX_COOLDOWN_MINS} minutes (e.g. 60) or seconds (e.g. 10s).",
                ephemeral=True,
            )
            return

        cfg = utils.get_config(interaction.guild_id)
        cfg.cooldown_secs = secs
        await db.save_config(utils.db_conn, cfg)
        await interaction.response.edit_message(view=ConfigView(cfg))


class PerksModal(discord.ui.Modal, title="Edit Awakener Perks"):
    perks = discord.ui.TextInput(
        label="One perk per line",
        style=discord.TextStyle.paragraph,
        placeholder="Priority in chat\nAccess to lounge\n…",
        max_length=config.PERKS_MAX_LENGTH,
        required=False,
    )

    def __init__(self, current_perks: str = "") -> None:
        super().__init__()
        self.perks.default = current_perks or None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        cfg = utils.get_config(interaction.guild_id)
        cfg.perks_text = "\n".join(line.strip() for line in str(self.perks).splitlines() if line.strip())
        await db.save_config(utils.db_conn, cfg)
        await interaction.response.edit_message(view=ConfigView(cfg))
