from ui.i18n import t
from ui.icons import Icons
from utils.logger import log

_FEEDBACK_ICONS = {
    # --- Errors ---
    "no_permission": Icons.ERROR,
    "admin_only": Icons.ERROR,
    "error_generic": Icons.ERROR,
    "error_resolve": Icons.ERROR,
    "no_playing_error": Icons.ERROR,
    "no_current_track": Icons.ERROR,
    # --- Warnings ---
    "not_in_same_voice": Icons.WARNING,
    "cannot_pause_stopped": Icons.WARNING,
    "cannot_seek_stopped": Icons.WARNING,
    "vol_range_error": Icons.WARNING,
    "format_error": Icons.WARNING,
    "too_long": Icons.WARNING,
    "cooldown_error": Icons.WARNING,
    "nothing_playing": Icons.WARNING,
    "invalid_number": Icons.WARNING,
    "empty": Icons.WARNING,
    "no_next_track": Icons.WARNING,
    "no_prev_track": Icons.WARNING,
    "wrong_channel_error": Icons.WARNING,
    # --- Status Messages ---
    "now_playing": Icons.HEADPHONES,
    "paused": Icons.PAUSE,
    "stopped": Icons.STOP,
    "buffering": Icons.BUFFERING,
    "idle": Icons.IDLE,
    "idle_status": Icons.IDLE,
    "resolving_link": "",
    # --- Headers / Titles ---
    "help_title": Icons.HELP,
    "search_results_title": Icons.SEARCH,
    "library_label": Icons.FOLDER_HEART,
    "history_label": Icons.HISTORY,
    "queue_label": Icons.QUEUE,
    "system_sync": Icons.SYNC,
    "system_settings": Icons.GEAR,
    "standby_mode": Icons.STANDBY,
    # --- Field Labels ---
    "uploader": "",
    "title": "",
    "duration": "",
    "source": "",
    "tuned_by": "",
    "unknown": "",
    # --- Processing / Waiting ---
    "search_processing": Icons.SEARCH,
    "syncing": Icons.SYNC,
    "severing": Icons.DISCONNECT,
    "resuming": Icons.PLAY,
    "forwarding": Icons.NEXT,
    "backing": Icons.BACK,
    "jumping": Icons.SEEK,
    "restarting": Icons.SYNC,
    # --- Success / Confirmation ---
    "weblink_added": Icons.SUCCESS,
    "vol_set": Icons.SUCCESS,
    "added_to_fav": Icons.HEART_PLUS,
    "removed_from_fav": Icons.HEART_MINUS,
    "added_all_to_queue": Icons.SUCCESS,
    "cleared_favorites": Icons.SWEEP,
    "cleared_history": Icons.SWEEP,
    "queue_shuffled": Icons.SWEEP,
    "resuming_feedback": Icons.PLAY,
    "pausing": Icons.PAUSE,
    "stopping": Icons.STOP,
    "loop_enabled": Icons.REPEAT,
    "loop_disabled": Icons.SUCCESS,
    "loop_queue_enabled": Icons.REPEAT,
    "loop_queue_disabled": Icons.SUCCESS,
}


def get_feedback(key: str, **kwargs) -> str:
    """Returns a translated UI feedback string prefixed with its domain icon."""
    emoji = _FEEDBACK_ICONS.get(key, "")
    text = t(key, **kwargs)

    if not text:
        log.warning(f"[UI] Missing translation key for feedback: {key}")
        return f"{emoji} {key}".strip()

    return f"{emoji} {text}".strip()

