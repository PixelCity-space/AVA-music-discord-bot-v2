import random

from core.models import Song


class QueueManager:
    """
    Manages playback queue ordering, loop modes, and browser-like history/future navigation.
    Isolated from Discord, VoiceClient, and FFmpeg so queue transitions can be tested directly.
    """

    def __init__(self):
        self.queue: list[Song] = []
        self.future_queue: list[Song] = []
        self.is_navigating: bool = False
        self.history_ptr: int = 0
        self.loop_mode: bool = False
        self.loop_queue_mode: bool = False

    def enqueue(self, song: Song):
        self.queue.append(song)

    def enqueue_many(self, songs: list[Song]):
        self.queue.extend(songs)

    def remove(self, song: Song) -> bool:
        if song in self.queue:
            self.queue.remove(song)
            return True
        return False

    def clear(self):
        self.queue = []

    def move(self, song: Song, direction: int) -> bool:
        try:
            idx = self.queue.index(song)
        except ValueError:
            return False
        new_idx = idx + direction
        if 0 <= new_idx < len(self.queue):
            self.queue[idx], self.queue[new_idx] = self.queue[new_idx], self.queue[idx]
            return True
        return False

    def shuffle(self):
        random.shuffle(self.queue)

    def toggle_loop(self) -> bool:
        self.loop_mode = not self.loop_mode
        if self.loop_mode:
            self.loop_queue_mode = False
        return self.loop_mode

    def toggle_loop_queue(self) -> bool:
        self.loop_queue_mode = not self.loop_queue_mode
        if self.loop_queue_mode:
            self.loop_mode = False
        return self.loop_queue_mode

    def reset_navigation(self):
        self.history_ptr = 0
        self.is_navigating = False

    def has_next(self) -> bool:
        return bool(self.queue or self.future_queue or self.is_navigating)

    def peek_next(self) -> Song | None:
        if self.future_queue:
            return self.future_queue[0]
        if self.queue:
            return self.queue[0]
        return None

    def select_next(self, current_song: Song | None) -> tuple[Song | None, bool]:
        """
        Selects the next song to play (or signals replaying the current track).
        Returns (selected_song, should_replay_from_start).
        """
        if self.loop_mode and current_song and not self.is_navigating:
            return current_song, True

        if self.future_queue:
            next_song = self.future_queue.pop(0)
            self.is_navigating = True
            self.history_ptr -= 1
            return next_song, False

        if self.queue:
            if self.loop_queue_mode and current_song and not self.is_navigating:
                self.queue.append(current_song)
            next_song = self.queue.pop(0)
            self.is_navigating = False
            self.history_ptr = 0
            return next_song, False

        if self.loop_queue_mode and current_song and not self.is_navigating:
            return current_song, True

        return None, False

    def step_back(self, history_manager, current_song: Song | None, during_playback: bool) -> Song | None:
        """
        Navigates one step backward in history, pushing current_song onto future_queue.
        Returns the historical Song if available, otherwise None.
        """
        if during_playback:
            next_ptr = self.history_ptr + (1 if self.is_navigating else 0)
        else:
            next_ptr = self.history_ptr + (1 if current_song else 0)

        back_song = history_manager.get_latest(offset=next_ptr)
        if not back_song:
            return None

        if current_song:
            self.future_queue.insert(0, current_song)
        self.history_ptr = next_ptr
        self.is_navigating = True
        return back_song

