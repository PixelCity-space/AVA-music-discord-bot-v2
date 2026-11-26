from typing import Optional
from discord.ui import ActionRow, Container, TextDisplay
from ui.components.list_controls import HistoryButton, LibraryButton
from ui.components.player_controls import (
    DisconnectButton,
    HelpButton,
    LanguageSelect,
    StationSelect,
    UIStyleSelect,
)
from ui.context import UIContext
from ui.feedback import get_feedback
from ui.i18n import t
from ui.theme import Theme
from ui.views.base import BaseView


def _add_station_controls(container: Container, radio, context: Optional[UIContext], prefix: str, tail_button):
    """Populates shared voice-channel, language, UI-style, and library rows onto a station container."""
    guild = context.get_guild() if context else None
    if not guild:
        return

    afk_id = radio.config.afk_channel_id
    v_channels = [c for c in sorted(guild.voice_channels, key=lambda c: c.position) if c.id != afk_id][:25]

    row_station = ActionRow()
    row_station.add_item(StationSelect(radio, v_channels, custom_id=f"{prefix}:station_select"))
    container.add_item(row_station)

    update_cb = context.update_callback if context else None
    row_lang = ActionRow()
    row_lang.add_item(LanguageSelect(radio, custom_id=f"{prefix}:language_select", update_callback=update_cb))
    container.add_item(row_lang)

    row_style = ActionRow()
    row_style.add_item(UIStyleSelect(radio, custom_id=f"{prefix}:uistyle_select", update_callback=update_cb))
    container.add_item(row_style)

    row_actions = ActionRow()
    row_actions.add_item(LibraryButton(radio, custom_id=f"{prefix}:library_button"))
    row_actions.add_item(HistoryButton(radio, custom_id=f"{prefix}:history_button"))
    row_actions.add_item(tail_button)
    container.add_item(row_actions)


class WelcomeLayout(BaseView):
    """Persistent standby station view shown when the bot is not connected to a voice channel."""

    def __init__(self, radio, context: Optional[UIContext] = None):
        super().__init__(radio)
        self.context = context

        header = Container(accent_color=Theme.BACKGROUND)
        welcome_text = f"**{get_feedback('system_sync')}**\n{t('synchro_subtitle')}"
        header.add_item(TextDisplay(welcome_text))
        _add_station_controls(header, radio, context, prefix="welcome", tail_button=HelpButton(radio))
        self.add_item(header)

        status_box = Container(accent_color=Theme.SECONDARY)
        status_box.add_item(TextDisplay(f"**{get_feedback('standby_mode')}**\n*{t('standby_subtitle')}*"))
        self.add_item(status_box)


class FrequencyStationView(BaseView):
    """Persistent station settings view shown while the bot is connected to a voice channel."""

    def __init__(self, radio, context: Optional[UIContext] = None):
        super().__init__(radio)
        self.context = context

        main = Container(accent_color=Theme.BACKGROUND)
        main.add_item(TextDisplay(f"**{get_feedback('system_settings')}**\n{t('synchro_settings_subtitle')}"))
        _add_station_controls(main, radio, context, prefix="station", tail_button=DisconnectButton(radio))
        self.add_item(main)

