from typing import Optional
from discord.ui import ActionRow, Container, Section, Separator, TextDisplay, Thumbnail
from core.actions import RadioState
from core.models import Song
from ui.components.list_controls import QueueViewButton
from ui.components.player_controls import (
    BackButton,
    FavoriteToggleButton,
    ForwardButton,
    PlayPauseButton,
    StopButton,
)
from ui.components.progress_bar import create_progress_bar
from ui.context import UIContext
from ui.feedback import get_feedback
from ui.i18n import t
from ui.modals.search import SearchButton
from ui.modals.seek import SeekButton
from ui.modals.volume import VolumeButton
from ui.modals.weblink import WebLinkButton
from ui.theme import Theme
from ui.utils import format_duration, truncate
from ui.views.base import BaseView


class NowPlayingView(BaseView):
    """Interactive Discord Components v2 player view showing current track metadata and controls."""

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
            f"**{get_feedback('title')}:** {title_display}",
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
            f"{progress_bar}",
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
