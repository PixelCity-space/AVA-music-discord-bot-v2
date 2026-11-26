from dataclasses import dataclass, replace

import discord

from core.actions import RadioAction, RadioState
from core.models import Song
from ui.feedback import get_feedback
from utils.logger import log


@dataclass
class CommandResult:
    feedback: str
    success: bool = True

class CommandService:
    """
    Unified command execution service for both Slash Commands and Prefix Commands.
    Centralizes validation, permission checking, action dispatching, and feedback generation.
    """
    def __init__(self, radio):
        self.radio = radio
        self.config = radio.config

    @staticmethod
    def _reject(user: discord.Member | discord.User, cmd: str, reason: str, feedback_key: str) -> CommandResult:
        log.debug(f"[CMD] Rejected '{cmd}' for {getattr(user, 'name', user)}: {reason}")
        return CommandResult(feedback=get_feedback(feedback_key), success=False)

    def play(self, user: discord.Member | discord.User, query: str | None = None) -> CommandResult:
        if not isinstance(user, discord.Member) or not user.voice or not user.voice.channel:
            return self._reject(user, "play", "user not in voice", "no_permission")

        if not self.radio.can_interact(user):
            return self._reject(user, "play", "not in same voice channel", "not_in_same_voice")

        if not query:
            if self.radio.status == RadioState.PAUSED:
                self.radio.dispatch(RadioAction.REPLAY, user=user)
                return CommandResult(feedback=get_feedback("resuming_feedback"))
            return self._reject(user, "play", f"empty query in status {self.radio.status.name}", "nothing_playing")

        url_strip = query.strip()
        if self.radio.voice_channel_id is None:
            self.radio.dispatch(RadioAction.JOIN, user.voice.channel.id, user=user)

        self.radio.dispatch(RadioAction.ADD_EXT_LINK, url_strip, user=user)
        return CommandResult(feedback=get_feedback("weblink_added"))

    def pause(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return self._reject(user, "pause", "not in same voice channel", "not_in_same_voice")

        if self.radio.status == RadioState.PLAYING:
            self.radio.dispatch(RadioAction.PAUSE, user=user)
            return CommandResult(feedback=get_feedback("pausing"))
        return self._reject(user, "pause", f"invalid status {self.radio.status.name}", "cannot_pause_stopped")

    def stop(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return self._reject(user, "stop", "not in same voice channel", "not_in_same_voice")

        self.radio.dispatch(RadioAction.STOP, user=user)
        return CommandResult(feedback=get_feedback("stopping"))

    def skip(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return self._reject(user, "skip", "not in same voice channel", "not_in_same_voice")

        if not self.radio.queue and not self.radio.future_queue and not self.radio.is_navigating:
            return self._reject(user, "skip", "no next track", "no_next_track")

        self.radio.dispatch(RadioAction.SKIP, user=user)
        return CommandResult(feedback=get_feedback("forwarding"))

    def back(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return self._reject(user, "back", "not in same voice channel", "not_in_same_voice")

        if not self.radio.has_history:
            return self._reject(user, "back", "no previous track", "no_prev_track")

        self.radio.dispatch(RadioAction.BACK, user=user)
        return CommandResult(feedback=get_feedback("backing"))

    def seek(self, user: discord.Member | discord.User, time_str: str) -> CommandResult:
        if not self.radio.can_interact(user):
            return self._reject(user, "seek", "not in same voice channel", "not_in_same_voice")

        if self.radio.status in [RadioState.IDLE, RadioState.STOPPED]:
            return self._reject(user, "seek", f"invalid status {self.radio.status.name}", "cannot_seek_stopped")

        if not self.radio.current_song:
            return self._reject(user, "seek", "no current track", "no_current_track")

        try:
            parts = time_str.strip().split(":")
            if len(parts) == 2:
                minutes, seconds = map(int, parts)
                if minutes < 0 or seconds < 0 or seconds >= 60:
                    return self._reject(user, "seek", f"out-of-range mm:ss '{time_str}'", "format_error")
                total_seconds = minutes * 60 + seconds
            elif len(parts) == 1:
                total_seconds = int(parts[0])
            else:
                return self._reject(user, "seek", f"invalid timestamp '{time_str}'", "format_error")
        except ValueError:
            return self._reject(user, "seek", f"unparseable timestamp '{time_str}'", "format_error")

        if total_seconds < 0:
            return self._reject(user, "seek", f"negative timestamp {total_seconds}", "format_error")

        if self.radio.current_song.duration > 0 and total_seconds > self.radio.current_song.duration:
            return self._reject(user, "seek", f"{total_seconds}s > duration {self.radio.current_song.duration}s", "too_long")

        self.radio.dispatch(RadioAction.SEEK, total_seconds, user=user)
        return CommandResult(feedback=f"{get_feedback('jumping')} {time_str}")

    def volume(self, user: discord.Member | discord.User, percent: int) -> CommandResult:
        if not self.radio.can_interact(user):
            return self._reject(user, "volume", "not in same voice channel", "not_in_same_voice")

        if 0 <= percent <= 100:
            self.radio.dispatch(RadioAction.SET_VOLUME, percent / 100, user=user)
            return CommandResult(feedback=f"{get_feedback('vol_set')} {percent}%")
        return self._reject(user, "volume", f"out-of-range volume {percent}", "vol_range_error")

    def loop(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return self._reject(user, "loop", "not in same voice channel", "not_in_same_voice")

        self.radio.dispatch(RadioAction.LOOP, user=user)
        msg_key = "loop_enabled" if not self.radio.loop_mode else "loop_disabled"
        return CommandResult(feedback=get_feedback(msg_key))

    def loop_queue(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return self._reject(user, "loop_queue", "not in same voice channel", "not_in_same_voice")

        self.radio.dispatch(RadioAction.LOOP_QUEUE, user=user)
        msg_key = "loop_queue_enabled" if not self.radio.loop_queue_mode else "loop_queue_disabled"
        return CommandResult(feedback=get_feedback(msg_key))

    def shuffle(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return self._reject(user, "shuffle", "not in same voice channel", "not_in_same_voice")

        self.radio.dispatch(RadioAction.SHUFFLE, user=user)
        return CommandResult(feedback=get_feedback("queue_shuffled"))

    def join(self, user: discord.Member | discord.User) -> CommandResult:
        if not isinstance(user, discord.Member) or not user.voice or not user.voice.channel:
            return self._reject(user, "join", "user not in voice", "no_permission")

        if not self.radio.can_interact(user):
            return self._reject(user, "join", "not in same voice channel", "not_in_same_voice")

        self.radio.dispatch(RadioAction.JOIN, user.voice.channel.id, user=user)
        return CommandResult(feedback=f"{get_feedback('syncing')} ({user.voice.channel.name})")

    def disconnect(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return self._reject(user, "disconnect", "not in same voice channel", "not_in_same_voice")

        self.radio.dispatch(RadioAction.DISCONNECT, user=user)
        return CommandResult(feedback=get_feedback("severing"))

    def enqueue_songs(self, user: discord.Member | discord.User, songs: list[Song]) -> CommandResult:
        if not self.radio.can_interact(user):
            return self._reject(user, "enqueue_songs", "not in same voice channel", "not_in_same_voice")

        if self.radio.voice_channel_id is None:
            user_voice = getattr(user, "voice", None)
            if not user_voice or not getattr(user_voice, "channel", None):
                return self._reject(user, "enqueue_songs", "user not in voice while bot disconnected", "no_permission")
            self.radio.dispatch(RadioAction.JOIN, user_voice.channel.id, user=user)

        q_songs = [
            replace(song, requested_by=user.display_name, _resolve_event=None)
            for song in songs
        ]
        self.radio.dispatch(RadioAction.ADD_SONGS, q_songs, user=user)
        return CommandResult(feedback=get_feedback("added_all_to_queue"))

    def clear_history(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.is_admin(user):
            return self._reject(user, "clear_history", "admin role required", "admin_only")

        self.radio.dispatch(RadioAction.CLEAR_HISTORY, user=user)
        return CommandResult(feedback=get_feedback("cleared_history"))

    def clear_cache(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.is_admin(user):
            return self._reject(user, "clear_cache", "admin role required", "admin_only")

        count = self.radio.clear_cache()
        return CommandResult(feedback=f"Cache cleared: {count} files removed.")

    def restart(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.is_admin(user):
            return self._reject(user, "restart", "admin role required", "admin_only")

        self.radio.dispatch(RadioAction.RESTART, user=user)
        return CommandResult(feedback=get_feedback("restarting"))
