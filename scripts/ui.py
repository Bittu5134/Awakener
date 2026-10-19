"""Embeds, persistent views, and the `/config` panel."""

from typing import cast

import discord

from . import config
from .db import GuildConfig, GuildState
from .utils import ConfigStore

COLOUR = discord.Colour.gold()


def _store(interaction: discord.Interaction) -> ConfigStore:
    return cast("ConfigStore", interaction.client)


def _config_for(store: ConfigStore, guild_id: int) -> GuildConfig:
    return store.configs.get(guild_id) or GuildConfig(guild_id=guild_id)


def _parse_cooldown(raw: str) -> int | None:
    """Parse minutes, or seconds when suffixed with 's' (e.g. 10s for testing)."""
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
    """Show e.g. '10s' or '60' in the modal prefill."""
    if secs % 60 == 0:
        return str(secs // 60)
    return f"{secs}s"


# --------------------------------------------------------------------------- #
# Embeds
# --------------------------------------------------------------------------- #


def build_status_text(guild: discord.Guild, store: ConfigStore) -> str:
    """Single-line plain-text message for /awakener."""
    cfg = store.configs.get(guild.id)
    state = store.states.get(guild.id)

    if cfg is None or not cfg.channel_id or not cfg.role_id:
        return "⚠️ Awakener is not configured yet. An admin can set it up with `/config`."

    role = guild.get_role(cfg.role_id)
    role_mention = role.mention if role else f"<@&{cfg.role_id}>"

    if state and state.current_holder_id:
        return f"{role_mention} is currently held by <@{state.current_holder_id}>."
    return f"{role_mention} is currently unclaimed."


def build_claim_text(author: discord.Member, role: discord.Role) -> str:
    """Single-line plain-text message when a silent chat is revived."""
    return f"{role.mention} has been claimed by {author.mention}!"


def build_info_embed(cfg: GuildConfig | None) -> discord.Embed:
    cooldown = config.format_cooldown(cfg.cooldown_secs) if cfg else "not set"
    channel = f"<#{cfg.channel_id}>" if cfg and cfg.channel_id else "not set"
    role = f"<@&{cfg.role_id}>" if cfg and cfg.role_id else "not set"
    return discord.Embed(
        title="🔥 The Awakener Role — How It Works",
        description=(
            "Revive a silent chat and claim the Awakener role.\n\n"
            "**Timer**\n"
            f"The channel must stay silent for **{cooldown}** before a message can "
            "claim the role.\n\n"
            "**How it works**\n"
            "The first person to speak after the silence claims the role. The "
            "previous holder loses it. Sending another message yourself while you "
            "hold the role does not re-claim it.\n\n"
            f"**Channel:** {channel}\n**Role:** {role}"
        ),
        colour=COLOUR,
    )


def build_perks_embed(cfg: GuildConfig | None) -> discord.Embed:
    perks = cfg.perks if cfg else []
    return discord.Embed(
        title="🔥 Awakener Perks",
        description=(
            "\n".join(f"• {perk}" for perk in perks)
            if perks
            else config.DEFAULT_PERKS_MESSAGE
        ),
        colour=COLOUR,
    )


def build_config_embed(cfg: GuildConfig) -> discord.Embed:
    perks = len(cfg.perks)
    embed = discord.Embed(
        title="⚙️ Awakener Configuration",
        description="Pick an option below — changes save instantly.",
        colour=COLOUR,
    )
    embed.add_field(
        name="Channel",
        value=f"<#{cfg.channel_id}>" if cfg.channel_id else "not set",
        inline=True,
    )
    embed.add_field(
        name="Role", value=f"<@&{cfg.role_id}>" if cfg.role_id else "not set", inline=True
    )
    embed.add_field(
        name="Cooldown", value=config.format_cooldown(cfg.cooldown_secs), inline=True
    )
    embed.add_field(
        name="Perks",
        value=f"{perks} configured" if perks else "none",
        inline=False,
    )
    return embed


# --------------------------------------------------------------------------- #
# Link button helpers
# --------------------------------------------------------------------------- #


def _add_external_links(view: discord.ui.View, row: int = 1) -> None:
    if config.INVITE_URL:
        view.add_item(
            discord.ui.Button(
                label="Invite",
                style=discord.ButtonStyle.link,
                url=config.INVITE_URL,
                emoji="📨",
                row=row,
            )
        )
    if config.PATREON_URL:
        view.add_item(
            discord.ui.Button(
                label="Patreon",
                style=discord.ButtonStyle.link,
                url=config.PATREON_URL,
                emoji="💖",
                row=row,
            )
        )


# --------------------------------------------------------------------------- #
# Public status view (used on /awakener and claim messages)
# --------------------------------------------------------------------------- #


class AwakenerStatusView(discord.ui.View):
    """Attached to `/awakener` and claim messages. Only Info and Perks buttons."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Info",
        style=discord.ButtonStyle.secondary,
        emoji="ℹ️",
        custom_id="awakener:info",
    )
    async def show_info(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        cfg = _store(interaction).configs.get(interaction.guild_id or 0)
        await interaction.response.send_message(
            embed=build_info_embed(cfg),
            view=InfoView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Perks",
        style=discord.ButtonStyle.secondary,
        emoji="🎁",
        custom_id="awakener:perks",
    )
    async def show_perks(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        cfg = _store(interaction).configs.get(interaction.guild_id or 0)
        await interaction.response.send_message(
            embed=build_perks_embed(cfg),
            view=PerksView(),
            ephemeral=True,
        )


class InfoView(discord.ui.View):
    """Attached to the Info embed: has Perks, Invite, Patreon (and optional Help)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        _add_external_links(self, row=1)

    @discord.ui.button(
        label="Perks",
        style=discord.ButtonStyle.secondary,
        emoji="🎁",
        custom_id="awakener:info_to_perks",
        row=0,
    )
    async def go_to_perks(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        cfg = _store(interaction).configs.get(interaction.guild_id or 0)
        await interaction.response.edit_message(
            embed=build_perks_embed(cfg),
            view=PerksView(),
        )


class PerksView(discord.ui.View):
    """Attached to the Perks embed: has Info, Invite, Patreon (and optional Help)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        _add_external_links(self, row=1)

    @discord.ui.button(
        label="Info",
        style=discord.ButtonStyle.secondary,
        emoji="ℹ️",
        custom_id="awakener:perks_to_info",
        row=0,
    )
    async def go_to_info(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        cfg = _store(interaction).configs.get(interaction.guild_id or 0)
        await interaction.response.edit_message(
            embed=build_info_embed(cfg),
            view=InfoView(),
        )


# --------------------------------------------------------------------------- #
# /config panel
# --------------------------------------------------------------------------- #


class ConfigView(discord.ui.View):
    """Persistent admin panel: channel/role selectors + cooldown & perks modals."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select the Awakener channel",
        custom_id="config:channel",
        row=0,
    )
    async def select_channel(
        self, interaction: discord.Interaction, select: discord.ui.ChannelSelect
    ) -> None:
        store = _store(interaction)
        guild_id = interaction.guild_id
        cfg = _config_for(store, guild_id)
        channel = select.values[0]

        if cfg.channel_id != channel.id:
            cfg.channel_id = channel.id
            await store.persist_config(cfg)
            state = store.states.get(guild_id) or GuildState(guild_id=guild_id)
            state.last_message_ts = None
            await store.persist_state(state)

        await interaction.response.edit_message(embed=build_config_embed(cfg))

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Select the Awakener role",
        custom_id="config:role",
        row=1,
    )
    async def select_role(
        self, interaction: discord.Interaction, select: discord.ui.RoleSelect
    ) -> None:
        store = _store(interaction)
        cfg = _config_for(store, interaction.guild_id)
        cfg.role_id = select.values[0].id
        await store.persist_config(cfg)
        await interaction.response.edit_message(embed=build_config_embed(cfg))

    @discord.ui.button(
        label="Set Cooldown",
        style=discord.ButtonStyle.primary,
        emoji="⏱️",
        custom_id="config:cooldown",
        row=2,
    )
    async def set_cooldown(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        store = _store(interaction)
        cfg = _config_for(store, interaction.guild_id)
        await interaction.response.send_modal(CooldownModal(cfg.cooldown_secs))

    @discord.ui.button(
        label="Edit Perks",
        style=discord.ButtonStyle.primary,
        emoji="📝",
        custom_id="config:perks",
        row=2,
    )
    async def edit_perks(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        store = _store(interaction)
        cfg = _config_for(store, interaction.guild_id)
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
                f"Invalid cooldown. Enter **{config.MIN_COOLDOWN_MINS}–"
                f"{config.MAX_COOLDOWN_MINS} minutes** (e.g. `60`), "
                "or `10s`–`21600s` for testing.",
                ephemeral=True,
            )
            return

        store = _store(interaction)
        cfg = _config_for(store, interaction.guild_id)
        cfg.cooldown_secs = secs
        await store.persist_config(cfg)
        await interaction.response.edit_message(embed=build_config_embed(cfg))


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
        store = _store(interaction)
        cfg = _config_for(store, interaction.guild_id)
        cfg.perks_text = "\n".join(
            line.strip() for line in str(self.perks).splitlines() if line.strip()
        )
        await store.persist_config(cfg)
        await interaction.response.edit_message(embed=build_config_embed(cfg))
