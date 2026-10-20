"""AwakenerBot: gateway client, slash command, and the claim flow."""

import logging

import aiosqlite
import discord
from discord import app_commands

from . import config, db, utils
from .ui import (
    AwakenerStatusView,
    ConfigView,
    InfoView,
    PerksView,
    build_claim_text,
    build_status_text,
)

log = logging.getLogger(__name__)


@app_commands.command(
    name="awakener", description="Show who currently holds the Awakener role"
)
@app_commands.guild_only()
async def awakener_command(interaction: discord.Interaction) -> None:
    bot = interaction.client
    assert isinstance(bot, AwakenerBot)
    text = build_status_text(interaction.guild, bot)
    await interaction.response.send_message(view=AwakenerStatusView(text))


@app_commands.command(name="config", description="Configure the Awakener bot")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def config_command(interaction: discord.Interaction) -> None:
    bot = interaction.client
    assert isinstance(bot, AwakenerBot)
    cfg = bot.configs.get(interaction.guild_id or 0)
    await interaction.response.send_message(
        view=ConfigView(cfg),
        ephemeral=True,
    )


class AwakenerBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        # Privileged. Requires the "Server Members Intent" toggle in the dev
        # portal; see https://discord.com/developers/applications/
        intents.members = True
        # message_content stays disabled: message text is never read.
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.db: aiosqlite.Connection | None = None
        self.configs: dict[int, db.GuildConfig] = {}
        self.states: dict[int, db.GuildState] = {}

    async def setup_hook(self) -> None:
        self.db = await db.open_db(config.DB_PATH)
        self.configs = await db.load_configs(self.db)
        self.states = await db.load_states(self.db)

        self.add_view(AwakenerStatusView())
        self.add_view(InfoView())
        self.add_view(PerksView())
        self.add_view(ConfigView())
        self.tree.add_command(awakener_command)
        self.tree.add_command(config_command)

        try:
            if config.GUILD_ID is not None:
                guild = discord.Object(id=config.GUILD_ID)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
            else:
                synced = await self.tree.sync()
            log.info("Synced %d slash command(s).", len(synced))
        except discord.HTTPException:
            log.exception("Failed to sync slash commands.")

    async def close(self) -> None:
        await db.close_db(self.db)
        self.db = None
        self.configs.clear()
        self.states.clear()
        await super().close()

    # persistence ----------------------------------------------------------- #

    async def persist_config(self, store_config: db.GuildConfig) -> None:
        assert self.db is not None
        self.configs[store_config.guild_id] = store_config
        await db.save_config(self.db, store_config)

    async def persist_state(self, state: db.GuildState) -> None:
        assert self.db is not None
        self.states[state.guild_id] = state
        await db.save_state(self.db, state)

    # gateway events --------------------------------------------------------- #

    async def on_ready(self) -> None:
        log.info("Logged in as %s — Awakener monitor active.", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.webhook_id is not None:
            return
        if message.guild is None:
            return

        store_config = self.configs.get(message.guild.id)
        if (
            store_config is None
            or not store_config.channel_id
            or not store_config.role_id
        ):
            return
        if message.channel.id != store_config.channel_id:
            return

        state = self.states.get(message.guild.id) or db.GuildState(
            guild_id=message.guild.id
        )
        now = discord.utils.utcnow()
        previous_ts = state.last_message_ts

        # If a claim message is still sitting there, delete it as soon as chat resumes.
        if state.last_claim_msg_id:
            old_id = state.last_claim_msg_id
            state.last_claim_msg_id = None
            try:
                msg_to_delete = await message.channel.fetch_message(old_id)
                await msg_to_delete.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        # Always book-keep the newest human message so the timer restarts.
        state.last_message_ts = now
        await self.persist_state(state)

        if previous_ts is None:
            return
        elapsed = (now - previous_ts).total_seconds()
        if elapsed < store_config.cooldown_secs:
            return
        if message.author.id == state.current_holder_id:
            return

        guild = message.guild
        role = guild.get_role(store_config.role_id)
        if role is None:
            log.warning("Guild %s: configured role is missing.", guild.id)
            return

        problem = utils.role_problem(guild, role)
        if problem:
            log.warning("Guild %s: %s", guild.id, problem)
            return

        await self._remove_role_from_previous_holder(
            guild, state.current_holder_id, role
        )

        try:
            await message.author.add_roles(role, reason="Revived a silent chat")
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning(
                "Guild %s: failed to assign the Awakener role (%s).", guild.id, exc
            )
            return

        state.current_holder_id = message.author.id
        await self.persist_state(state)

        text = build_claim_text(message.author, role)
        print(text)
        try:
            claim_msg = await message.channel.send(
                content=text,
                view=AwakenerStatusView(),
                reference=message,
                mention_author=False,
                silent=True,
            )
            state.last_claim_msg_id = claim_msg.id
            await self.persist_state(state)
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning(
                "Guild %s: failed to send the claim message (%s).", guild.id, exc
            )

    async def _remove_role_from_previous_holder(
        self, guild: discord.Guild, holder_id: int | None, role: discord.Role
    ) -> None:
        if not holder_id:
            return

        member = guild.get_member(holder_id)  # needs the Members intent cache
        if member is None:
            # No Members intent (or not cached): REST lookup still works.
            try:
                member = await guild.fetch_member(holder_id)
            except (discord.NotFound, discord.HTTPException) as exc:
                log.warning(
                    "Guild %s: previous holder %s unavailable (%s).",
                    guild.id,
                    holder_id,
                    exc,
                )
                return

        if role not in member.roles:
            return

        try:
            await member.remove_roles(role, reason="Chat awakened by someone else")
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning(
                "Guild %s: failed to remove the role from the previous holder (%s).",
                guild.id,
                exc,
            )


# aiosqlite.Connection type is only needed for annotations.
