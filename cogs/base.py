"""
Base cog module providing shared functionality and channel validation for all RadioBot cogs.
"""

import discord
from discord.ext import commands

from ui.feedback import get_feedback
from ui.utils import respond


class BaseRadioCog(commands.Cog):
    """Base class for all RadioBot cogs with shared interaction and channel validation."""
    
    def __init__(self, bot):
        self.bot = bot
        self.radio = bot.radio

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensures commands are executed in the designated radio text channel."""
        if interaction.channel_id != self.radio.config.radio_text_channel_id:
            await respond(interaction, get_feedback("wrong_channel_error"), ephemeral=True)
            return False
        return True
