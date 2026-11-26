import asyncio
import discord
from discord.ui import Modal, TextInput
from ui.icons import Icons
from ui.i18n import t
from ui.utils import get_feedback, safe_delete_message
from ui.views.base import handle_ui_error
from ui.views.search_results import SearchResultsView
from core.models import Song
from utils.logger import log

class SearchButton(discord.ui.Button):
    def __init__(self, radio):
        super().__init__(
            label=None if radio.is_compact else t('search_label'),
            emoji=Icons.SEARCH,
            style=discord.ButtonStyle.secondary,
            custom_id="search_modal_open"
        )
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        modal = SearchModal(self.radio)
        await interaction.response.send_modal(modal)

class SearchModal(Modal):
    def __init__(self, radio):
        super().__init__(title=t("search_modal_title"))
        self.radio = radio
        self.query_input = TextInput(
            label=t("search_input_label"),
            placeholder=t('search_placeholder'),
            style=discord.TextStyle.short,
            required=True,
            min_length=2
        )
        self.add_item(self.query_input)

    @handle_ui_error
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        query = self.query_input.value.strip()
        
        msg = await interaction.followup.send(get_feedback("search_processing"), ephemeral=True)
        log.info(f"[SEARCH] User {interaction.user.name} searched for: {query}")
        
        results = []
        for provider in self.radio.providers:
            if hasattr(provider, 'search'):
                provider_results = await provider.search(query, limit=self.radio.config.search_limit)
                results.extend([Song.from_dict(res) for res in provider_results])
        
        if not results:
            log.info(f"[SEARCH] No results found for: {query}")
            await interaction.followup.send(get_feedback("empty"), ephemeral=True)
            return

        log.info(f"[SEARCH] Found {len(results)} results for: {query}")

        await asyncio.to_thread(self.radio.db.set_cache_batch, [song.to_dict() for song in results])

        view = SearchResultsView(self.radio, results, query=query, user=interaction.user)
        await interaction.followup.send(view=view, ephemeral=True)
        await safe_delete_message(msg)
