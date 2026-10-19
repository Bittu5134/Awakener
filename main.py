import os
import json
import discord

intents = discord.Intents.default()
client = discord.Client(intents=intents)

CHANNEL_ID = 1387002318247034900
ROLE_ID = 1106806475080335410
MESSAGE_COOLDOWN = 5
MESSAGE_EMBED = (
    '{"description": "🔥 {{author}} revived the chat and claimed '
    'the {{role}} role!"}'
)

last_message_timestamp = None
last_message_author_id = 818428347151024199
last_sent_message = None


@client.event
async def on_ready():
    global last_message_timestamp, last_sent_message
    last_message_timestamp = discord.utils.utcnow()
    last_sent_message = None
    print(f"Logged in as {client.user} - Awakener monitor active.")


@client.event
async def on_message(message: discord.Message):
    global last_message_timestamp, last_message_author_id, last_sent_message

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
            if message.author.id == last_message_author_id:
                last_message_timestamp = now
                return

            guild = message.guild
            role = guild.get_role(ROLE_ID)

            if role:
                if last_message_author_id:
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
                    embed_data = MESSAGE_EMBED
                    placeholders = {
                        "{{author}}": message.author.mention,
                        "{{role}}": role.mention,
                    }
                    for placeholder, value in placeholders.items():
                        embed_data = embed_data.replace(placeholder, value)

                    embed = discord.Embed.from_dict(json.loads(embed_data))
                    if last_sent_message is not None:
                        try:
                            await last_sent_message.delete()
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            pass

                    last_sent_message = await message.channel.send(
                        embed=embed,
                        reference=message,
                        mention_author=False,
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

                last_message_author_id = message.author.id

    last_message_timestamp = now


client.run(os.getenv("DISCORD_TOKEN"))
