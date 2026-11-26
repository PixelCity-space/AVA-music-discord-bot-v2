import discord
from discord.ui import (
    ActionRow, Container, Section, 
    TextDisplay, Thumbnail, Separator
)
from ui.i18n import t
from ui.theme import Theme
from ui.utils import format_duration, get_feedback, truncate
from ui.views.base import BaseView
from ui.components.progress_bar import create_progress_bar
from ui.components.player_controls import (
    StationSelect,
    LanguageSelect,
    UIStyleSelect,
    DisconnectButton,
    PlayPauseButton,
    StopButton,
    ForwardButton,
    BackButton,
    FavoriteToggleButton,
    HelpButton
)
from ui.components.list_controls import LibraryButton, HistoryButton, QueueViewButton
from ui.modals.weblink import WebLinkButton
from ui.modals.search import SearchButton
from ui.modals.seek import SeekButton
from ui.modals.volume import VolumeButton
from core.actions import RadioState
from core.models import Song
from ui.context import UIContext
from typing import Optional

class HelpView:
    def __init__(self, radio):
        self.radio = radio
        self.config = radio.config

    def get_embed(self) -> discord.Embed:
        prefix = self.config.command_prefix
        embed = discord.Embed(
            title=get_feedback('help_title'),
            description=t("help_description"),
            color=Theme.PRIMARY
        )
        
        commands = [
            ("play [url/search]", t("help_play_desc")),
            ("pause", t("help_pause_desc")),
            ("stop", t("help_stop_desc")),
            ("skip", t("help_skip_desc")),
            ("back", t("help_back_desc")),
            ("volume [0-100]", t("help_vol_desc")),
            ("seek [time]", t("help_seek_desc")),
            ("queue", t("help_queue_desc")),
            ("join", t("help_join_desc")),
            ("disconnect", t("help_leave_desc")),
            ("loop", t("help_loop_desc")),
            ("loopq", t("help_loopq_desc")),
            ("shuffle", t("help_shuffle_desc"))
        ]
        
        for cmd, desc in commands:
            embed.add_field(name=f"`/{cmd}` vagy `{prefix}{cmd}`", value=desc, inline=False)
            
        return embed

class WelcomeLayout(BaseView):
    def __init__(self, radio, context: Optional[UIContext] = None):
        super().__init__(radio)
        self.context = context
        embed_color = Theme.BACKGROUND
        
        header = Container(accent_color=embed_color)
        welcome_text = f"**{get_feedback('system_sync')}**\n{t('synchro_subtitle')}"
        header.add_item(TextDisplay(welcome_text))
        
        guild = context.get_guild() if context else None
        if guild:
            afk_id = radio.config.afk_channel_id
            v_channels = [c for c in sorted(guild.voice_channels, key=lambda c: c.position) if c.id != afk_id][:25]
            row_station = ActionRow()
            row_station.add_item(StationSelect(radio, v_channels, custom_id="welcome:station_select"))
            header.add_item(row_station)
            
            update_cb = context.update_callback if context else None
            row_lang = ActionRow()
            row_lang.add_item(LanguageSelect(radio, custom_id="welcome:language_select", update_callback=update_cb))
            header.add_item(row_lang)
            
            row_style = ActionRow()
            row_style.add_item(UIStyleSelect(radio, custom_id="welcome:uistyle_select", update_callback=update_cb))
            header.add_item(row_style)
            
            row_lib = ActionRow()
            row_lib.add_item(LibraryButton(radio, custom_id="welcome:library_button"))
            row_lib.add_item(HistoryButton(radio, custom_id="welcome:history_button"))
            row_lib.add_item(HelpButton(radio))
            header.add_item(row_lib)

        self.add_item(header)
        
        status_box = Container(accent_color=Theme.SECONDARY)
        status_box.add_item(TextDisplay(f"**{get_feedback('standby_mode')}**\n*{t('standby_subtitle')}*"))
        self.add_item(status_box)

class FrequencyStationView(BaseView):
    def __init__(self, radio, context: Optional[UIContext] = None):
        super().__init__(radio)
        self.context = context
        main = Container(accent_color=Theme.BACKGROUND)
        main.add_item(TextDisplay(f"**{get_feedback('system_settings')}**\n{t('synchro_settings_subtitle')}"))
        
        guild = context.get_guild() if context else None
        if guild:
            afk_id = radio.config.afk_channel_id
            v_channels = [c for c in sorted(guild.voice_channels, key=lambda c: c.position) if c.id != afk_id][:25]
            row_select = ActionRow()
            row_select.add_item(StationSelect(radio, v_channels, custom_id="station:station_select"))
            main.add_item(row_select)
            
            update_cb = context.update_callback if context else None
            row_lang = ActionRow()
            row_lang.add_item(LanguageSelect(radio, custom_id="station:language_select", update_callback=update_cb))
            main.add_item(row_lang)
            
            row_style = ActionRow()
            row_style.add_item(UIStyleSelect(radio, custom_id="station:uistyle_select", update_callback=update_cb))
            main.add_item(row_style)
            
            mgmt_row = ActionRow()
            mgmt_row.add_item(LibraryButton(radio, custom_id="station:library_button"))
            mgmt_row.add_item(HistoryButton(radio, custom_id="station:history_button"))
            mgmt_row.add_item(DisconnectButton(radio))
            main.add_item(mgmt_row)
            
        self.add_item(main)

class NowPlayingView(BaseView):
    def __init__(self, radio, song: Song | None = None, context: Optional[UIContext] = None):
        super().__init__(radio)
        self.context = context
        song = song or radio.current_song
        
        if radio.status == RadioState.PLAYING:
            accent_color = Theme.PLAYING
        elif radio.status == RadioState.PAUSED:
            accent_color = Theme.PAUSED
        elif radio.status == RadioState.STOPPED:
            accent_color = Theme.STOPPED
        elif radio.status == RadioState.BUFFERING:
            accent_color = Theme.BUFFERING
        else:
            accent_color = Theme.IDLE

        status_key = "now_playing"
        if radio.status == RadioState.PAUSED:
            status_key = "paused"
        elif radio.status == RadioState.STOPPED:
            status_key = "stopped"
        elif radio.status == RadioState.BUFFERING:
            status_key = "buffering"
        elif radio.status == RadioState.IDLE:
            status_key = "idle"
            if not song or not song.path:
                status_key = "idle_status"

        status_display = get_feedback(status_key)
        master = Container(accent_color=accent_color)
        
        if song and song.is_resolving and not song.title:
            title = t("resolving_link")
        else:
            title = song.title if song else t("unknown")
        uploader = (song.uploader if song else None) or t("unknown")
        
        truncated_title = truncate(title, radio.config.max_title_len)
        truncated_uploader = truncate(uploader, radio.config.max_uploader_len)

        source = song.source if song else None
        if not source and song and song.webpage_url:
            if "youtube.com" in song.webpage_url or "youtu.be" in song.webpage_url:
                source = "YouTube"
            elif "soundcloud.com" in song.webpage_url:
                source = "SoundCloud"
        
        title_display = truncated_title
        web_url = song.webpage_url if song else None
        if web_url:
            title_display = f"[{truncated_title}]({web_url})"

        info_lines = [
            f"**{status_display}**",
            f"**{get_feedback('uploader')}:** {truncated_uploader}",
            f"**{get_feedback('title')}:** {title_display}"
        ]
        if source:
            info_lines.append(f"**{t('source')}:** {source}")
            
        mode_text = None
        if radio.loop_mode:
            mode_text = t("loop_track_label")
        elif radio.loop_queue_mode:
            mode_text = t("loop_queue_label")
            
        if mode_text:
            info_lines.append(f"**{t('mode_label')}:** {mode_text}")
        
        elapsed = int(radio.elapsed_seconds)
        duration = song.duration if song else 0
        
        time_readout = f"`{format_duration(elapsed)} / {format_duration(duration) if duration else t('unknown')}`"
        progress_bar = create_progress_bar(elapsed, duration, width=radio.config.progress_bar_width)
        info_lines.extend([
            f"\n{time_readout}\n",
            f"{progress_bar}"
        ])
        
        if radio.last_user:
            channel_name = ""
            if radio.voice and radio.voice.channel:
                channel_name = f" @ {radio.voice.channel.mention}"
            elif radio.voice_channel_id:
                channel_name = " @ ..."
                
            info_lines.append(f"\n{t('tuned_by')} {radio.last_user.mention}{channel_name}")

        thumb = None
        thumb_url = song.thumbnail_url if song else None
        if not thumb_url and radio.status == RadioState.IDLE and context and context.bot_user:
            thumb_url = str(context.bot_user.display_avatar.url)
        
        if thumb_url:
            thumb = Thumbnail(thumb_url)

        if thumb:
            master.add_item(Section("\n".join(info_lines), accessory=thumb))
        else:
            master.add_item(TextDisplay("\n".join(info_lines)))
        
        master.add_item(Separator())
        
        row1 = ActionRow()
        row1.add_item(BackButton(radio))
        row1.add_item(PlayPauseButton(radio))
        row1.add_item(StopButton(radio))
        row1.add_item(ForwardButton(radio))
        row1.add_item(FavoriteToggleButton(radio, song))
        master.add_item(row1)
        
        row2 = ActionRow()
        row2.add_item(SeekButton(radio))
        row2.add_item(VolumeButton(radio))
        row2.add_item(SearchButton(radio))
        row2.add_item(WebLinkButton(radio, custom_id="player:weblink_button"))
        row2.add_item(QueueViewButton(radio))
        master.add_item(row2)
        
        self.add_item(master)
