import discord
from discord.ext import tasks
import os

intents = discord.Intents.default()
client = discord.Client(intents=intents)

MESSAGE_COOLDOWN = 5 

last_message_id = None
last_message_author = 818428347151024199
last_message_timestamp = None
role_id = 1106806475080335410
channel_id = 1387002318247034900


@client.event
async def on_ready():
    print(f"We have logged in as {client.user}")
    if not bg_task.is_running():
        bg_task.start()


@tasks.loop(seconds=2)
async def bg_task():
    global last_message_author, last_message_id
    try:
        channel = client.get_channel(channel_id)
        if channel is None:
            return

        message = None
        async for candidate in channel.history(limit=100):
            if not candidate.author.bot:
                message = candidate
                break
        if message is None:
            return

        if message.id == last_message_id:
            return

        if (discord.utils.utcnow() - message.created_at).total_seconds() < MESSAGE_COOLDOWN:
            return

        guild = channel.guild
        role = guild.get_role(role_id)
        if role is None:
            return

        previous_author = guild.get_member(last_message_author)
        if previous_author is None:
            try:
                previous_author = await guild.fetch_member(last_message_author)
            except discord.NotFound:
                previous_author = None

        if previous_author is not None:
            await previous_author.remove_roles(role)

        member = guild.get_member(message.author.id) or await guild.fetch_member(
            message.author.id
        )
        await member.add_roles(role)
        last_message_author = member.id
        last_message_id = message.id
    except Exception as error:
        print(f"Background task error: {error}")


client.run(os.getenv("DISCORD_TOKEN"))
