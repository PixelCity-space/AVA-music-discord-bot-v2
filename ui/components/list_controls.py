"""
Interactive Discord UI buttons for playlist, queue, favorites, and history manipulation.
"""

import discord
from typing import Optional, List
from ui.icons import Icons
from ui.i18n import t
from ui.feedback import get_feedback
from ui.utils import respond
from ui.views.base import handle_ui_error
from core.actions import RadioAction, RadioState
from core.models import Song
from utils.logger import log

class SearchResultAddButton(discord.ui.Button):
    """Button to enqueue a track directly from search results."""
    def __init__(self, radio, result: Song):
        super().__init__(emoji=Icons.ADD, style=discord.ButtonStyle.secondary)
        self.radio = radio
        self.result = result

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.radio.dispatch(RadioAction.ADD_EXT_LINK, self.result.path, user=interaction.user)
        await respond(interaction, get_feedback("weblink_added"), delete_after=self.radio.config.notification_timeout)

class FavoriteListButton(discord.ui.Button):
    """Button to toggle favorite status of a song within a list view."""
    def __init__(self, radio, song: Song, user_id: Optional[int] = None):
        as_fav = False
        if user_id:
            as_fav = radio.fav_manager.is_favorite(user_id, song)
            
        emoji = Icons.HEART_MINUS if as_fav else Icons.HEART_PLUS
        super().__init__(emoji=emoji, style=discord.ButtonStyle.secondary)
        self.radio = radio
        self.song = song

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        is_fav_now = self.radio.fav_manager.is_favorite(interaction.user.id, self.song)
        will_be_added = not is_fav_now

        self.radio.dispatch(RadioAction.TOGGLE_FAVORITE, (interaction.user.id, self.song), user=interaction.user)
        
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        try:
            if hasattr(self.view, 'refresh_view'):
                await self.view.refresh_view(interaction)
            else:
                await interaction.edit_original_response(view=self.view)
        except Exception as e:
            log.debug(f"[UI] Favorite refresh failed: {e}")

        key = "added_to_fav" if will_be_added else "removed_from_fav"
        await respond(interaction, get_feedback(key), delete_after=self.radio.config.notification_timeout)

class FavoriteRemoveButton(discord.ui.Button):
    """Button to remove an individual song from favorites."""
    def __init__(self, radio, song: Song):
        super().__init__(emoji=Icons.REMOVE, style=discord.ButtonStyle.secondary)
        self.radio = radio
        self.song = song

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        self.radio.fav_manager.toggle_favorite(interaction.user.id, self.song)
        await interaction.response.defer(ephemeral=True)
        if hasattr(self.view, 'refresh_view'):
            await self.view.refresh_view(interaction)
        await respond(interaction, get_feedback('removed_from_fav'), delete_after=self.radio.config.notification_timeout)

class LibraryButton(discord.ui.Button):
    """Button to open the personal favorites library modal / view."""
    def __init__(self, radio, custom_id="library_button"):
        super().__init__(
            label=None if radio.is_compact else t('library_label'),
            emoji=Icons.FOLDER_HEART,
            style=discord.ButtonStyle.secondary,
            custom_id=custom_id
        )
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        from ui.views.favorites import FavoritesView
        view = FavoritesView(self.radio, interaction.user.id)
        await interaction.response.send_message(view=view, ephemeral=True)

class AddAllFavoritesButton(discord.ui.Button):
    """Button to enqueue all tracks from user's favorites into the playback queue."""
    def __init__(self, radio, songs: List[Song]):
        super().__init__(
            label=t("add_all_to_queue"),
            emoji=Icons.QUEUE,
            style=discord.ButtonStyle.secondary
        )
        self.radio = radio
        self.songs = songs

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        res = self.radio.command_service.enqueue_songs(interaction.user, self.songs)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)

class ClearFavoritesButton(discord.ui.Button):
    """Button to purge all tracks from user's favorites list."""
    def __init__(self, radio, user_id: str | int):
        super().__init__(
            label=t("clear_favorites"),
            emoji=Icons.SWEEP,
            style=discord.ButtonStyle.secondary
        )
        self.radio = radio
        self.user_id = user_id

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        self.radio.dispatch(RadioAction.CLEAR_FAVORITES, self.user_id, user=interaction.user)
        await interaction.response.defer()
        if hasattr(self.view, 'refresh_view'):
            self.view.current_page = 0
            self.view.data_list = []
            await self.view.refresh_view(interaction)
            
        await respond(interaction, get_feedback('cleared_favorites'), delete_after=self.radio.config.notification_timeout)

class HistoryButton(discord.ui.Button):
    """Button to open the playback history view."""
    def __init__(self, radio, custom_id="history_button"):
        super().__init__(
            label=None if radio.is_compact else t('history_label'),
            emoji=Icons.HISTORY,
            style=discord.ButtonStyle.secondary,
            custom_id=custom_id
        )
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        from ui.views.history import HistoryView
        view = HistoryView(self.radio, user=interaction.user)
        await interaction.response.send_message(view=view, ephemeral=True)

class ClearHistoryButton(discord.ui.Button):
    """Button to purge the playback history log (Admin only)."""
    def __init__(self, radio):
        super().__init__(
            label=t("clear_history_label"), 
            emoji=Icons.SWEEP, 
            style=discord.ButtonStyle.secondary
        )
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        res = self.radio.command_service.clear_history(interaction.user)
        if not res.success:
            await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)
            return

        await interaction.response.defer()
        if hasattr(self.view, 'refresh_view'):
            self.view.current_page = 0
            self.view.data_list = []
            await self.view.refresh_view(interaction)

        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)

class QueueViewButton(discord.ui.Button):
    """Button to open the full paginated queue view."""
    def __init__(self, radio):
        is_idle_empty = (radio.status == RadioState.IDLE) and (not radio.queue)
        super().__init__(
            label=None if radio.is_compact else t('queue_label'), 
            emoji=Icons.QUEUE, 
            style=discord.ButtonStyle.secondary, 
            custom_id="full_queue_view",
            disabled=is_idle_empty
        )
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        from ui.views.queue import FullQueueView
        view = FullQueueView(self.radio, page=0, user=interaction.user)
        await interaction.response.send_message(view=view, ephemeral=True)

class RemoveFromQueueButton(discord.ui.Button):
    """Button to remove an individual song from the upcoming queue."""
    def __init__(self, radio, song: Song):
        super().__init__(emoji=Icons.REMOVE, style=discord.ButtonStyle.secondary)
        self.radio = radio
        self.song = song

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.radio.dispatch(RadioAction.REMOVE_FROM_QUEUE, self.song, user=interaction.user)
        if hasattr(self.view, 'refresh_view'):
            await self.view.refresh_view(interaction)

class ClearQueueButton(discord.ui.Button):
    """Button to remove all songs from the upcoming queue."""
    def __init__(self, radio):
        super().__init__(label=t("clear_queue_label"), emoji=Icons.SWEEP, style=discord.ButtonStyle.secondary)
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.radio.dispatch(RadioAction.CLEAR_QUEUE, user=interaction.user)
        if hasattr(self.view, 'refresh_view'):
            self.view.current_page = 0
            await self.view.refresh_view(interaction)

class MoveUpButton(discord.ui.Button):
    """Button to shift a track one position earlier in the queue."""
    def __init__(self, radio, song: Song, is_first: bool = False):
        super().__init__(emoji=Icons.MOVE_UP, style=discord.ButtonStyle.secondary, disabled=is_first)
        self.radio = radio
        self.song = song

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.radio.dispatch(RadioAction.MOVE_SONG, (self.song, -1), user=interaction.user)
        if hasattr(self.view, 'refresh_view'):
            await self.view.refresh_view(interaction)

class MoveDownButton(discord.ui.Button):
    """Button to shift a track one position later in the queue."""
    def __init__(self, radio, song: Song, is_last: bool = False):
        super().__init__(emoji=Icons.MOVE_DOWN, style=discord.ButtonStyle.secondary, disabled=is_last)
        self.radio = radio
        self.song = song

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.radio.dispatch(RadioAction.MOVE_SONG, (self.song, 1), user=interaction.user)
        if hasattr(self.view, 'refresh_view'):
            await self.view.refresh_view(interaction)
