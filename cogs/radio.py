"""
Voice channel connectivity and volume slash commands cog for RadioBot.
"""

import discord
from discord import app_commands

from cogs.base import BaseRadioCog
from ui.utils import respond


class RadioCog(BaseRadioCog):
    """Cog handling voice channel connection, disconnection, and volume adjustment."""
    @app_commands.command(name="join", description="Connect the bot to your current voice channel")
    async def join(self, interaction: discord.Interaction):
        res = self.radio.command_service.join(interaction.user)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)

    @app_commands.command(name="disconnect", description="Disconnect the bot from voice")
    async def disconnect(self, interaction: discord.Interaction):
        res = self.radio.command_service.disconnect(interaction.user)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)

    @app_commands.command(name="volume", description="Adjust bot playback volume (0-100)")
    @app_commands.describe(percent="Volume percentage 0 to 100")
    async def volume(self, interaction: discord.Interaction, percent: int):
        res = self.radio.command_service.volume(interaction.user, percent)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)

async def setup(bot):
    await bot.add_cog(RadioCog(bot))
