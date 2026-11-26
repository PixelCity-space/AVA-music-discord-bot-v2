"""
Administrative slash commands cog for RadioBot cache management and process restart.
"""

import discord
from discord import app_commands

from cogs.base import BaseRadioCog
from ui.utils import respond


class AdminCog(BaseRadioCog):
    """Cog handling administrator-restricted commands such as clearing cache and restarting."""
    @app_commands.command(name="clearcache", description="Clears the local audio cache (Admin only)")
    async def clear_cache(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        res = self.radio.command_service.clear_cache(interaction.user)
        await respond(interaction, res.feedback, ephemeral=True)

    @app_commands.command(name="restart", description="Restart the bot process (Admin only)")
    async def restart(self, interaction: discord.Interaction):
        res = self.radio.command_service.restart(interaction.user)
        await respond(interaction, res.feedback, ephemeral=True)

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
