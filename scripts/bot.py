import logging

import discord
from discord import app_commands

from . import config, db, utils
from .ui import (
    AwakenerStatusView,
    ConfigView,
    InfoView,
    PerksView,
)

log = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.members = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


@tree.command(name="awaken", description="Show who currently holds the Awakener role")
@app_commands.guild_only()
async def awaken_command(interaction: discord.Interaction) -> None:
    text = utils.get_status_text(interaction.guild)
    await interaction.response.send_message(content=text, view=AwakenerStatusView())


@tree.command(name="config", description="Configure the Awakener bot")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def config_command(interaction: discord.Interaction) -> None:
    cfg = utils.configs.get(interaction.guild_id) or db.GuildConfig(
        guild_id=interaction.guild_id
    )
    await interaction.response.send_message(view=ConfigView(cfg), ephemeral=True)


@bot.event
async def setup_hook():
    utils.db_conn = await db.open_db(config.DB_PATH)
    utils.configs = await db.load_configs(utils.db_conn)
    utils.states = await db.load_states(utils.db_conn)

    bot.add_view(AwakenerStatusView())
    bot.add_view(InfoView())
    bot.add_view(PerksView())
    bot.add_view(ConfigView())

    if config.GUILD_ID:
        guild = discord.Object(id=config.GUILD_ID)
        tree.copy_global_to(guild=guild)
        synced = await tree.sync(guild=guild)
    else:
        synced = await tree.sync()
    log.info("Synced %d slash command(s).", len(synced))


@bot.event
async def on_ready():
    log.info("Logged in as %s", bot.user)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.webhook_id or not message.guild:
        return

    cfg = utils.configs.get(message.guild.id)
    if (
        not cfg
        or not cfg.channel_id
        or not cfg.role_id
        or message.channel.id != cfg.channel_id
    ):
        return

    state = utils.states.setdefault(
        message.guild.id, db.GuildState(guild_id=message.guild.id)
    )
    now = discord.utils.utcnow()
    previous_ts = state.last_message_ts

    if not previous_ts or (now - previous_ts).total_seconds() < cfg.cooldown_secs:
        return
    if message.author.id == state.current_holder_id:
        return

    role = message.guild.get_role(cfg.role_id)
    if not role or utils.role_problem(message.guild, role):
        return

    # Delete the previous claim message if it exists
    if state.last_claim_msg_id:
        try:
            msg = await message.channel.fetch_message(state.last_claim_msg_id)
            await msg.delete()
        except Exception:
            pass
        state.last_claim_msg_id = None

    state.last_message_ts = now
    await db.save_state(utils.db_conn, state)

    # Remove role from previous holder and add it to the new holder
    if state.current_holder_id:
        prev = message.guild.get_member(
            state.current_holder_id
        ) or await message.guild.fetch_member(state.current_holder_id)
        if prev and role in prev.roles:
            try:
                await prev.remove_roles(role, reason="Managed by Awakener bot")
            except Exception:
                pass

    try:
        await message.author.add_roles(role, reason="Managed by Awakener bot")
    except Exception:
        return

    state.current_holder_id = message.author.id

    try:
        claim_msg = await message.channel.send(
            content=f"{role.mention} has been claimed by {message.author.mention}!",
            view=AwakenerStatusView(),
            reference=message,
            mention_author=False,
            silent=True,
        )
        state.last_claim_msg_id = claim_msg.id
    except Exception:
        pass

    await db.save_state(utils.db_conn, state)
