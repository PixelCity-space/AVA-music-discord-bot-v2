"""
Queue and playback mode slash commands cog for RadioBot.
"""

import discord
from discord import app_commands
from cogs.base import BaseRadioCog
from ui.feedback import get_feedback
from ui.utils import respond
from ui.views.queue import FullQueueView

class QueueCog(BaseRadioCog):
    """Cog handling queue inspection, single track looping, queue looping, and queue shuffling."""
    @app_commands.command(name="queue", description="Show the full upcoming song queue")
    async def queue(self, interaction: discord.Interaction):
        if not self.radio.can_interact(interaction.user):
            await respond(interaction, get_feedback("not_in_same_voice"), delete_after=self.radio.config.notification_timeout)
            return
        view = FullQueueView(self.radio, page=0, user=interaction.user)
        await respond(interaction, view=view)

    @app_commands.command(name="loop", description="Toggle single track loop mode")
    async def loop(self, interaction: discord.Interaction):
        res = self.radio.command_service.loop(interaction.user)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)

    @app_commands.command(name="loopq", description="Toggle full queue loop mode")
    async def loopq(self, interaction: discord.Interaction):
        res = self.radio.command_service.loop_queue(interaction.user)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)

    @app_commands.command(name="shuffle", description="Randomize the upcoming queue order")
    async def shuffle(self, interaction: discord.Interaction):
        res = self.radio.command_service.shuffle(interaction.user)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)

async def setup(bot):
    await bot.add_cog(QueueCog(bot))
