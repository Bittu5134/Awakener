"""Helpers for resolving channels/roles and validating configuration."""

from typing import Coroutine, Protocol

import discord

from .db import GuildConfig, GuildState


class ConfigStore(Protocol):
    """What UI code expects from the bot object (avoids circular imports)."""

    configs: dict[int, GuildConfig]
    states: dict[int, GuildState]

    def persist_config(
        self, config: GuildConfig
    ) -> Coroutine[object, object, None]: ...

    def persist_state(self, state: GuildState) -> Coroutine[object, object, None]: ...


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
    if role >= me.top_role:
        return (
            "That role is above (or equal to) the bot's highest role. "
            "Move the bot's role higher in Server Settings → Roles."
        )
    return None
