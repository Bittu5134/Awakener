import os
import discord

intents = discord.Intents.default()
client = discord.Client(intents=intents)

CHANNEL_ID = 1387002318247034900
ROLE_ID = 1106806475080335410
MESSAGE_COOLDOWN = 5

last_message_timestamp = None
last_message_author_id = 818428347151024199


@client.event
async def on_ready():
    global last_message_timestamp
    last_message_timestamp = discord.utils.utcnow()
    print(f"Logged in as {client.user} - Awakener monitor active.")


@client.event
async def on_message(message: discord.Message):
    global last_message_timestamp, last_message_author_id

    if (
        message.author.bot
        or message.webhook_id is not None
        or message.channel.id != CHANNEL_ID
    ):
        return

    now = discord.utils.utcnow()

    if last_message_timestamp is not None:
        elapsed = (now - last_message_timestamp).total_seconds()

        if elapsed >= MESSAGE_COOLDOWN:
            guild = message.guild
            role = guild.get_role(ROLE_ID)

            if role:
                if (
                    last_message_author_id
                    and last_message_author_id != message.author.id
                ):
                    prev_member = guild.get_member(last_message_author_id)
                    if prev_member is None:
                        try:
                            prev_member = await guild.fetch_member(
                                last_message_author_id
                            )
                        except (discord.NotFound, discord.HTTPException):
                            prev_member = None

                    if prev_member and role in prev_member.roles:
                        try:
                            await prev_member.remove_roles(
                                role, reason="Chat awakened by someone else"
                            )
                        except (discord.Forbidden, discord.HTTPException):
                            pass

                try:
                    await message.author.add_roles(role, reason="Revived silent chat")
                    await message.channel.send(
                        f"🔥 {message.author.mention} revived the chat after "
                        f"{int(elapsed // 60)} minutes of silence and claimed the **{role.name}** role!"
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

                last_message_author_id = message.author.id


    last_message_timestamp = now


client.run(os.getenv("DISCORD_TOKEN"))
