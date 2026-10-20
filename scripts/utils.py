import discord

from .db import GuildConfig, GuildState

configs: dict[int, GuildConfig] = {}
states: dict[int, GuildState] = {}
db_conn = None


def get_config(guild_id: int) -> GuildConfig:
    if guild_id not in configs:
        configs[guild_id] = GuildConfig(guild_id=guild_id)
    return configs[guild_id]


def get_state(guild_id: int) -> GuildState:
    if guild_id not in states:
        states[guild_id] = GuildState(guild_id=guild_id)
    return states[guild_id]


def get_status_text(guild: discord.Guild) -> str:
    cfg = configs.get(guild.id)
    if not cfg or not cfg.role_id or not cfg.channel_id:
        return "⚠️ Awakener is not configured yet. An admin can set it up with `/config`."

    state = states.get(guild.id)
    holder = f"<@{state.current_holder_id}>" if state and state.current_holder_id else None
    return f"<@&{cfg.role_id}> is currently held by {holder}." if holder else f"<@&{cfg.role_id}> is currently unclaimed."


def role_problem(guild: discord.Guild, role: discord.Role) -> str | None:
    if role.is_default():
        return "The @everyone role can't be used."
    if role.managed:
        return "That role is managed by an integration."
    if role >= guild.me.top_role:
        return "Move the bot's role higher in Server Settings → Roles."
    return None
