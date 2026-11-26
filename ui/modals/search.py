import asyncio
import discord
from discord.ui import Modal, TextInput
from ui.icons import Icons
from ui.i18n import t
from ui.feedback import get_feedback
from ui.utils import safe_delete_message
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
        search_coros = [
            provider.search(query, limit=self.radio.config.search_limit)
            for provider in self.radio.providers
            if hasattr(provider, "search")
        ]
        if search_coros:
            provider_batches = await asyncio.gather(*search_coros, return_exceptions=True)
            for batch in provider_batches:
                if isinstance(batch, Exception):
                    log.warning(f"[SEARCH] Provider search failed: {batch}")
                    continue
                results.extend([Song.from_dict(res) for res in batch])

        if not results:
            log.info(f"[SEARCH] No results found for: {query}")
            await asyncio.gather(
                interaction.followup.send(get_feedback("empty"), ephemeral=True),
                safe_delete_message(msg),
            )
            return

        log.info(f"[SEARCH] Found {len(results)} results for: {query}")

        await asyncio.to_thread(self.radio.db.set_cache_batch, [song.to_dict() for song in results])

        view = SearchResultsView(self.radio, results, query=query, user=interaction.user)
        await asyncio.gather(
            interaction.followup.send(view=view, ephemeral=True),
            safe_delete_message(msg),
        )
