from dataclasses import dataclass
from typing import Optional
import discord
from core.actions import RadioAction, RadioState
from ui.utils import get_feedback

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

    def play(self, user: discord.Member | discord.User, query: Optional[str] = None) -> CommandResult:
        if not isinstance(user, discord.Member) or not user.voice:
            return CommandResult(feedback=get_feedback("no_permission"), success=False)

        if not self.radio.can_interact(user):
            return CommandResult(feedback=get_feedback("not_in_same_voice"), success=False)

        if not query:
            if self.radio.status == RadioState.PAUSED:
                self.radio.dispatch(RadioAction.REPLAY, user=user)
                return CommandResult(feedback=get_feedback("resuming_feedback"))
            else:
                return CommandResult(feedback=get_feedback("nothing_playing"), success=False)

        url_strip = query.strip()
        if self.radio.voice_channel_id is None:
            self.radio.dispatch(RadioAction.JOIN, user.voice.channel.id, user=user)

        self.radio.dispatch(RadioAction.ADD_EXT_LINK, url_strip, user=user)
        return CommandResult(feedback=get_feedback("weblink_added"))

    def pause(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return CommandResult(feedback=get_feedback("not_in_same_voice"), success=False)

        if self.radio.status == RadioState.PLAYING:
            self.radio.dispatch(RadioAction.PAUSE, user=user)
            return CommandResult(feedback=get_feedback("pausing"))
        else:
            return CommandResult(feedback=get_feedback("cannot_pause_stopped"), success=False)

    def stop(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return CommandResult(feedback=get_feedback("not_in_same_voice"), success=False)

        self.radio.dispatch(RadioAction.STOP, user=user)
        return CommandResult(feedback=get_feedback("stopping"))

    def skip(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return CommandResult(feedback=get_feedback("not_in_same_voice"), success=False)

        if not self.radio.queue and not self.radio.future_queue and not self.radio.is_navigating:
            return CommandResult(feedback=get_feedback("no_next_track"), success=False)

        self.radio.dispatch(RadioAction.SKIP, user=user)
        return CommandResult(feedback=get_feedback("forwarding"))

    def back(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return CommandResult(feedback=get_feedback("not_in_same_voice"), success=False)

        if not self.radio.has_history:
            return CommandResult(feedback=get_feedback("no_prev_track"), success=False)

        self.radio.dispatch(RadioAction.BACK, user=user)
        return CommandResult(feedback=get_feedback("backing"))

    def seek(self, user: discord.Member | discord.User, time_str: str) -> CommandResult:
        if not self.radio.can_interact(user):
            return CommandResult(feedback=get_feedback("not_in_same_voice"), success=False)

        if self.radio.status in [RadioState.IDLE, RadioState.STOPPED]:
            return CommandResult(feedback=get_feedback("cannot_seek_stopped"), success=False)

        if not self.radio.current_song:
            return CommandResult(feedback=get_feedback("no_current_track"), success=False)

        try:
            parts = time_str.split(":")
            if len(parts) == 2:
                minutes, seconds = map(int, parts)
                total_seconds = minutes * 60 + seconds
            else:
                total_seconds = int(time_str)
        except Exception:
            return CommandResult(feedback=get_feedback("format_error"), success=False)

        if total_seconds < 0:
            return CommandResult(feedback=get_feedback("format_error"), success=False)

        if self.radio.current_song.duration > 0 and total_seconds > self.radio.current_song.duration:
            return CommandResult(feedback=get_feedback("too_long"), success=False)

        self.radio.dispatch(RadioAction.SEEK, total_seconds, user=user)
        return CommandResult(feedback=f"{get_feedback('jumping')} {time_str}")

    def volume(self, user: discord.Member | discord.User, percent: int) -> CommandResult:
        if not self.radio.can_interact(user):
            return CommandResult(feedback=get_feedback("not_in_same_voice"), success=False)

        if 0 <= percent <= 100:
            self.radio.dispatch(RadioAction.SET_VOLUME, percent / 100, user=user)
            return CommandResult(feedback=f"{get_feedback('vol_set')} {percent}%")
        else:
            return CommandResult(feedback=get_feedback("vol_range_error"), success=False)

    def loop(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return CommandResult(feedback=get_feedback("not_in_same_voice"), success=False)

        self.radio.dispatch(RadioAction.LOOP, user=user)
        msg_key = "loop_enabled" if not self.radio.loop_mode else "loop_disabled"
        return CommandResult(feedback=get_feedback(msg_key))

    def loop_queue(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return CommandResult(feedback=get_feedback("not_in_same_voice"), success=False)

        self.radio.dispatch(RadioAction.LOOP_QUEUE, user=user)
        msg_key = "loop_queue_enabled" if not self.radio.loop_queue_mode else "loop_queue_disabled"
        return CommandResult(feedback=get_feedback(msg_key))

    def shuffle(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return CommandResult(feedback=get_feedback("not_in_same_voice"), success=False)

        self.radio.dispatch(RadioAction.SHUFFLE, user=user)
        return CommandResult(feedback=get_feedback("queue_shuffled"))

    def join(self, user: discord.Member | discord.User) -> CommandResult:
        if not isinstance(user, discord.Member) or not user.voice:
            return CommandResult(feedback=get_feedback("no_permission"), success=False)

        if not self.radio.can_interact(user):
            return CommandResult(feedback=get_feedback("not_in_same_voice"), success=False)

        self.radio.dispatch(RadioAction.JOIN, user.voice.channel.id, user=user)
        return CommandResult(feedback=f"{get_feedback('syncing')} ({user.voice.channel.name})")

    def disconnect(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.can_interact(user):
            return CommandResult(feedback=get_feedback("not_in_same_voice"), success=False)

        self.radio.dispatch(RadioAction.DISCONNECT, user=user)
        return CommandResult(feedback=get_feedback("severing"))

    def clear_cache(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.is_admin(user):
            return CommandResult(feedback=get_feedback("admin_only"), success=False)

        count = self.radio.clear_cache()
        return CommandResult(feedback=f"Cache cleared: {count} files removed.")

    def restart(self, user: discord.Member | discord.User) -> CommandResult:
        if not self.radio.is_admin(user):
            return CommandResult(feedback=get_feedback("admin_only"), success=False)

        self.radio.dispatch(RadioAction.RESTART, user=user)
        return CommandResult(feedback=get_feedback("restarting"))
