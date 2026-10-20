import discord

from . import config, db, utils
from .db import GuildConfig, GuildState

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


def _nav_button(label: str, emoji: str, custom_id: str, callback) -> discord.ui.Button:
    btn = discord.ui.Button(
        label=label,
        emoji=emoji,
        style=discord.ButtonStyle.secondary,
        custom_id=custom_id,
    )
    btn.callback = callback
    return btn


def _link_buttons() -> list[discord.ui.Button]:
    buttons = []
    if config.INVITE_URL:
        buttons.append(
            discord.ui.Button(
                label="Invite",
                emoji="📨",
                style=discord.ButtonStyle.link,
                url=config.INVITE_URL,
            )
        )
    if config.PATREON_URL:
        buttons.append(
            discord.ui.Button(
                label="Patreon",
                emoji="💖",
                style=discord.ButtonStyle.link,
                url=config.PATREON_URL,
            )
        )
    return buttons


class AwakenerStatusView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(_nav_button("Info", "ℹ️", "awakener:info", self.show_info))
        self.add_item(_nav_button("Perks", "🎁", "awakener:perks", self.show_perks))

    async def show_info(self, interaction: discord.Interaction) -> None:
        cfg = utils.get_config(interaction.guild_id)
        await interaction.response.send_message(view=InfoView(cfg), ephemeral=True)

    async def show_perks(self, interaction: discord.Interaction) -> None:
        cfg = utils.get_config(interaction.guild_id)
        await interaction.response.send_message(view=PerksView(cfg), ephemeral=True)


class InfoView(discord.ui.LayoutView):
    def __init__(self, cfg: GuildConfig | None = None) -> None:
        super().__init__(timeout=None)
        cooldown = config.format_cooldown(cfg.cooldown_secs) if cfg else "not set"
        channel = f"<#{cfg.channel_id}>" if cfg and cfg.channel_id else "not set"
        role = f"<@&{cfg.role_id}>" if cfg and cfg.role_id else "not set"

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("### ℹ️ The Awakener"),
                discord.ui.TextDisplay(
                    f"**Timer:** the channel must be silent for **{cooldown}** before a message claims the role.\n"
                    "**Rules:** the first to speak after silence claims it, and the previous holder loses it. "
                    "Sending again while you hold it does nothing."
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(f"-# {channel} · {role}"),
                discord.ui.ActionRow(
                    _nav_button("Perks", "🎁", "awakener:info_to_perks", self.go_perks),
                    *_link_buttons(),
                ),
                accent_colour=COLOUR,
            )
        )

    async def go_perks(self, interaction: discord.Interaction) -> None:
        cfg = utils.get_config(interaction.guild_id)
        await interaction.response.edit_message(view=PerksView(cfg))


class PerksView(discord.ui.LayoutView):
    def __init__(self, cfg: GuildConfig | None = None) -> None:
        super().__init__(timeout=None)
        perks = cfg.perks if cfg else []
        body = (
            "\n".join(f"• {p}" for p in perks)
            if perks
            else config.DEFAULT_PERKS_MESSAGE
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("### 🎁 Awakener Perks"),
                discord.ui.TextDisplay(body),
                discord.ui.ActionRow(
                    _nav_button("Info", "ℹ️", "awakener:perks_to_info", self.go_info),
                    *_link_buttons(),
                ),
                accent_colour=COLOUR,
            )
        )

    async def go_info(self, interaction: discord.Interaction) -> None:
        cfg = utils.get_config(interaction.guild_id)
        await interaction.response.edit_message(view=InfoView(cfg))


class ConfigView(discord.ui.LayoutView):
    def __init__(self, cfg: GuildConfig | None = None) -> None:
        super().__init__(timeout=None)
        cfg = cfg or GuildConfig(guild_id=0)

        channel_display = (
            f"<#{cfg.channel_id}>" if cfg.channel_id else "*None selected*"
        )
        role_display = f"<@&{cfg.role_id}>" if cfg.role_id else "*None selected*"
        cooldown_display = config.format_cooldown(cfg.cooldown_secs)
        perks_count = len(cfg.perks)
        perks_display = f"{perks_count} configured" if perks_count else "*None*"

        # Channel Selector
        self.channel_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text],
            placeholder="Select Awakener channel...",
            custom_id="config:channel",
        )
        self.channel_select.callback = self.on_channel

        # Role Selector
        self.role_select = discord.ui.RoleSelect(
            placeholder="Select Awakener role...",
            custom_id="config:role",
        )
        self.role_select.callback = self.on_role

        # Action Buttons
        cooldown_btn = discord.ui.Button(
            label=f"Cooldown ({cooldown_display})",
            emoji="⏱️",
            style=discord.ButtonStyle.secondary,
            custom_id="config:cooldown",
        )
        cooldown_btn.callback = self.on_cooldown

        perks_btn = discord.ui.Button(
            label=f"Perks ({perks_display})",
            emoji="📝",
            style=discord.ButtonStyle.secondary,
            custom_id="config:perks",
        )
        perks_btn.callback = self.on_perks

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("## ⚙️ Awakener Settings"),
                discord.ui.TextDisplay(
                    "-# Configure which channel to monitor, which role to grant, and chat revival timers."
                ),
                discord.ui.Separator(),
                # Section 1: Channel
                discord.ui.TextDisplay(f"**Channel** • Currently: {channel_display}"),
                discord.ui.ActionRow(self.channel_select),
                discord.ui.TextDisplay(
                    "-# ℹ️ Chat silence will be tracked exclusively inside this channel."
                ),
                # Section 2: Role
                discord.ui.TextDisplay(
                    f"**Awakener Role** • Currently: {role_display}"
                ),
                discord.ui.ActionRow(self.role_select),
                discord.ui.TextDisplay(
                    "-# ℹ️ The bot gives this role to the revival user and removes it from the previous holder."
                ),
                # Section 3: Cooldown & Perks
                discord.ui.TextDisplay("**Timer & Perks**"),
                discord.ui.ActionRow(cooldown_btn, perks_btn),
                discord.ui.TextDisplay(
                    "-# ℹ️ Changes save live instantly to the database."
                ),
                accent_colour=COLOUR,
            )
        )

    async def on_channel(self, interaction: discord.Interaction) -> None:
        cfg = utils.get_config(interaction.guild_id)
        selected_channel = self.channel_select.values[0]

        if cfg.channel_id != selected_channel.id:
            cfg.channel_id = selected_channel.id
            await db.save_config(utils.db_conn, cfg)
            state = utils.states.setdefault(
                cfg.guild_id, GuildState(guild_id=cfg.guild_id)
            )
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
        label="Minutes (5–360), or seconds (e.g. 10s)",
        placeholder="60  •  10s for testing  •  360",
        max_length=10,
    )

    def __init__(self, current_secs: int = config.DEFAULT_COOLDOWN_SECS) -> None:
        super().__init__()
        self.cooldown.default = _format_cooldown_input(current_secs)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        secs = _parse_cooldown(str(self.cooldown))
        if secs is None:
            await interaction.response.send_message(
                f"Invalid cooldown. Enter **{config.MIN_COOLDOWN_MINS}–{config.MAX_COOLDOWN_MINS} minutes** (e.g. `60`), or `10s`–`21600s` for testing.",
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
        placeholder="Priority in #general\nAccess to the lounge channel\n…",
        max_length=config.PERKS_MAX_LENGTH,
        required=False,
    )

    def __init__(self, current_perks: str = "") -> None:
        super().__init__()
        self.perks.default = current_perks or None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        cfg = utils.get_config(interaction.guild_id)
        cfg.perks_text = "\n".join(
            line.strip() for line in str(self.perks).splitlines() if line.strip()
        )
        await db.save_config(utils.db_conn, cfg)
        await interaction.response.edit_message(view=ConfigView(cfg))
