import os
import discord

intents = discord.Intents.default()
client = discord.Client(intents=intents)

CHANNEL_ID = 1387002318247034900
ROLE_ID = 1106806475080335410
MESSAGE_COOLDOWN = 5

last_message_timestamp = None
last_message_author_id = 818428347151024199


class AwakenerView(discord.ui.LayoutView):
    def __init__(self, author: discord.Member | None = None, role: discord.Role | None = None):
        super().__init__(timeout=None)

        info_button = discord.ui.Button(
            label="Info",
            style=discord.ButtonStyle.secondary,
            custom_id="awakener:info",
        )
        info_button.callback = self.show_info

        perks_button = discord.ui.Button(
            label="Perks",
            style=discord.ButtonStyle.primary,
            custom_id="awakener:perks",
        )
        perks_button.callback = self.show_perks

        delete_button = discord.ui.Button(
            label="Delete",
            style=discord.ButtonStyle.danger,
            custom_id="awakener:delete",
        )
        delete_button.callback = self.delete_message

        text = (
            f"### The chat was revived by {author.mention} and the {role.mention} role was claimed!"
            if author is not None and role is not None
            else "### Awakener"
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(text),
                discord.ui.ActionRow(info_button, perks_button, delete_button),
            )
        )

    async def show_info(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "This message revives the chat and assigns the Awakener role.",
            ephemeral=True,
        )

    async def show_perks(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "The Awakener role gives access to its configured perks.",
            ephemeral=True,
        )

    async def delete_message(self, interaction: discord.Interaction):
        await interaction.message.delete()


@client.event
async def on_ready():
    global last_message_timestamp
    last_message_timestamp = discord.utils.utcnow()
    client.add_view(AwakenerView())
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
                    await message.channel.send(
                        view=AwakenerView(message.author, role),
                        reference=message,
                        mention_author=False,
                        silent=True
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

                last_message_author_id = message.author.id

    last_message_timestamp = now


client.run(os.getenv("DISCORD_TOKEN"))
