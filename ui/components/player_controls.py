"""
Interactive Discord UI controls for playback orchestration (buttons, selects, station tuning).
"""

import discord
from ui.icons import Icons
from ui.i18n import t
from ui.feedback import get_feedback
from ui.utils import respond
from ui.views.base import handle_ui_error
from core.actions import RadioAction, RadioState
from core.models import Song
from utils.logger import log

class StationSelect(discord.ui.Select):
    """Dropdown menu for selecting and switching voice channels (stations)."""
    def __init__(self, radio, channels, custom_id="station_select"):
        self.radio = radio
        options = [
            discord.SelectOption(label=c.name, value=str(c.id), emoji=Icons.RADIO) for c in channels
        ]
        super().__init__(
            placeholder=t("placeholder_freq"),
            min_values=1,
            max_values=1,
            options=options,
            custom_id=custom_id
        )

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        channel_id = int(self.values[0])
        self.radio.dispatch(RadioAction.JOIN, channel_id, user=interaction.user)
        if not interaction.response.is_done():
            await interaction.response.defer()

class LanguageSelect(discord.ui.Select):
    """Dropdown menu for switching bot localization / language."""
    def __init__(self, radio, custom_id="language_select", update_callback=None):
        self.radio = radio
        self.update_callback = update_callback
        options = [
            discord.SelectOption(
                label=lang["label"], 
                value=lang["code"], 
                emoji=lang.get("emoji")
            ) for lang in radio.config.languages
        ]
        super().__init__(
            placeholder=t("placeholder_lang"),
            min_values=1,
            max_values=1,
            options=options,
            custom_id=custom_id
        )

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        self.radio.language = selected
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        if self.update_callback:
            await self.update_callback(self.radio.current_song)

class UIStyleSelect(discord.ui.Select):
    """Dropdown menu for toggling UI compactness (Full vs Compact mode)."""
    def __init__(self, radio, custom_id="uistyle_select", update_callback=None):
        self.radio = radio
        self.update_callback = update_callback
        options = [
            discord.SelectOption(label=t("full_mode_label"), value="full", description=t("full_mode_desc")),
            discord.SelectOption(label=t("compact_mode_label"), value="compact", description=t("compact_mode_desc"))
        ]
        super().__init__(
            placeholder=t("style_placeholder"),
            min_values=1,
            max_values=1,
            options=options,
            custom_id=custom_id
        )

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        self.radio.is_compact = (selected == "compact")
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        if self.update_callback:
            await self.update_callback(self.radio.current_song)

class DisconnectButton(discord.ui.Button):
    """Button to disconnect the bot from the current voice channel."""
    def __init__(self, radio):
        super().__init__(
            label=t('sever_uplink'),
            emoji=Icons.DISCONNECT,
            style=discord.ButtonStyle.secondary,
            custom_id="disconnect_button"
        )
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        self.radio.dispatch(RadioAction.DISCONNECT, user=interaction.user)
        await respond(interaction, get_feedback("severing"), delete_after=self.radio.config.notification_timeout)

class PlayPauseButton(discord.ui.Button):
    """Button to toggle between play/resume and pause states."""
    def __init__(self, radio):
        is_paused = radio.status in [RadioState.PAUSED, RadioState.STOPPED, RadioState.IDLE]
        label = None if radio.is_compact else (t('play_label') if is_paused else t('pause_label'))
        emoji = Icons.PLAY if is_paused else Icons.PAUSE
        is_idle_empty = (radio.status == RadioState.IDLE) and (not radio.queue)
        
        super().__init__(
            label=label,
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            custom_id="play_pause_toggle",
            disabled=is_idle_empty
        )
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        if self.radio.status in [RadioState.PAUSED, RadioState.STOPPED, RadioState.IDLE]:
            self.radio.dispatch(RadioAction.REPLAY, user=interaction.user)
            await respond(interaction, get_feedback("resuming_feedback"), delete_after=self.radio.config.notification_timeout)
        else:
            self.radio.dispatch(RadioAction.PAUSE, user=interaction.user)
            await respond(interaction, get_feedback("pausing"), delete_after=self.radio.config.notification_timeout)

class StopButton(discord.ui.Button):
    """Button to stop audio playback and clear active stream."""
    def __init__(self, radio):
        is_disabled = radio.status in [RadioState.IDLE, RadioState.STOPPED]
        super().__init__(
            label=None if radio.is_compact else t('stop_label'),
            emoji=Icons.STOP,
            style=discord.ButtonStyle.secondary,
            custom_id="stop_button",
            disabled=is_disabled
        )
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        self.radio.dispatch(RadioAction.STOP, user=interaction.user)
        await respond(interaction, get_feedback("stopping"), delete_after=self.radio.config.notification_timeout)

class ForwardButton(discord.ui.Button):
    """Button to skip forward to the next song in queue or navigation stack."""
    def __init__(self, radio):
        super().__init__(
            label=None if radio.is_compact else t('forward_label'),
            emoji=Icons.SKIP,
            style=discord.ButtonStyle.secondary,
            custom_id="forward_button",
            disabled=(not radio.queue and not radio.future_queue and not radio.is_navigating)
        )
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        self.radio.dispatch(RadioAction.SKIP, user=interaction.user)
        await respond(interaction, get_feedback("forwarding"), delete_after=self.radio.config.notification_timeout)

class BackButton(discord.ui.Button):
    """Button to step backward into playback history."""
    def __init__(self, radio):
        super().__init__(
            label=None if radio.is_compact else t('back_label'),
            emoji=Icons.BACK,
            style=discord.ButtonStyle.secondary,
            custom_id="back_button",
            disabled=(not radio.has_history)
        )
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        self.radio.dispatch(RadioAction.BACK, user=interaction.user)
        await respond(interaction, get_feedback("backing"), delete_after=self.radio.config.notification_timeout)

class FavoriteToggleButton(discord.ui.Button):
    """Button to toggle the current song in user favorites."""
    def __init__(self, radio, song: Song | None):
        is_fav = False
        target_user_id = (str(radio.last_user.id) if radio.last_user else None) or (song.user_id if song else None)
        
        if song and target_user_id:
            is_fav = radio.fav_manager.is_favorite(target_user_id, song)
            
        emoji = Icons.HEART_MINUS if is_fav else Icons.HEART_PLUS
        label = None if radio.is_compact else (t('fav_remove_label') if is_fav else t('fav_add_label'))
        
        super().__init__(
            label=label,
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            custom_id="player:favorite_toggle",
            disabled=(not song or song.is_resolving)
        )
        self.radio = radio
        self.song = song

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        if not self.song:
            return
            
        added = self.radio.fav_manager.toggle_favorite(interaction.user.id, self.song)
        self.emoji = Icons.HEART_MINUS if added else Icons.HEART_PLUS
        
        if not self.radio.is_compact:
            self.label = t('fav_remove_label') if added else t('fav_add_label')
        
        key = "added_to_fav" if added else "removed_from_fav"
        await respond(interaction, get_feedback(key), delete_after=self.radio.config.notification_timeout)
        
        try:
            await interaction.message.edit(view=self.view)
        except Exception as e:
            log.debug(f"[UI] Could not refresh player view: {e}")

class HelpButton(discord.ui.Button):
    """Button to display the radio help and commands embed."""
    def __init__(self, radio):
        super().__init__(
            label=t("help_label"),
            emoji=Icons.HELP,
            style=discord.ButtonStyle.secondary,
            custom_id="welcome:help"
        )
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        from ui.views.help import HelpView
        view = HelpView(self.radio)
        await respond(interaction, embed=view.get_embed())
