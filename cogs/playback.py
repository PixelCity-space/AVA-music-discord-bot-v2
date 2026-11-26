"""
Audio playback control slash commands cog for RadioBot.
"""


import discord
from discord import app_commands

from cogs.base import BaseRadioCog
from ui.utils import respond


class PlaybackCog(BaseRadioCog):
    """Cog managing playback controls including play, pause, stop, skip, back, and seek."""
    @app_commands.command(name="play", description="Start or resume playback, or add a link/search query")
    @app_commands.describe(url="YouTube/SoundCloud link or search keywords")
    async def play(self, interaction: discord.Interaction, url: str | None = None):
        if url:
            await interaction.response.defer(ephemeral=True)
        res = self.radio.command_service.play(interaction.user, url)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)

    @app_commands.command(name="pause", description="Pause the current song")
    async def pause(self, interaction: discord.Interaction):
        res = self.radio.command_service.pause(interaction.user)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)

    @app_commands.command(name="stop", description="Stop playback and clear current track")
    async def stop(self, interaction: discord.Interaction):
        res = self.radio.command_service.stop(interaction.user)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)

    @app_commands.command(name="skip", description="Skip to the next song in queue")
    async def skip(self, interaction: discord.Interaction):
        res = self.radio.command_service.skip(interaction.user)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)

    @app_commands.command(name="back", description="Navigate back to the previous track in history")
    async def back(self, interaction: discord.Interaction):
        res = self.radio.command_service.back(interaction.user)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)

    @app_commands.command(name="seek", description="Seek to a timestamp (mm:ss or seconds)")
    @app_commands.describe(time="Timestamp e.g. 01:30 or 90")
    async def seek(self, interaction: discord.Interaction, time: str):
        res = self.radio.command_service.seek(interaction.user, time)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)

async def setup(bot):
    await bot.add_cog(PlaybackCog(bot))
