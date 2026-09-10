import discord
import asyncio
from ui.icons import Icons
from ui.i18n import t
from utils.logger import log

async def delayed_delete(item: discord.Message | discord.Interaction | None, delay: float = 20.0):
    if not item:
        return
    
    await asyncio.sleep(delay)
    try:
        if isinstance(item, discord.Interaction):
            await item.delete_original_response()
        elif isinstance(item, discord.Message):
            await item.delete()
    except Exception:
        pass

def get_feedback(key: str, **kwargs) -> str:
    """
    Returns a translated string prefixed with the appropriate emoji.
    """
    icons_map = {
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
    
    emoji = icons_map.get(key, "")
    text = t(key, **kwargs)
    
    if not text:
        log.warning(f"[UI] Missing translation key for feedback: {key}")
        return f"{emoji} {key}".strip()
        
    return f"{emoji} {text}".strip()

async def respond(interaction: discord.Interaction, content=None, embed=None, view=None, ephemeral=True, delete_after: float | None = None):
    """
    Modularized interaction responder. 
    Handles both initial response and followup automatically.
    If delete_after is provided, the message will be scheduled for deletion.
    """
    kwargs = {"ephemeral": ephemeral}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view
    
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(**kwargs)
            target = interaction
        else:
            msg = await interaction.followup.send(**kwargs)
            target = msg
            
        if delete_after:
            asyncio.create_task(delayed_delete(target, delete_after))
    except Exception as e:
        log.error(f"UI Respond error: {e}")

def format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"

def truncate(text: str | None, max_len: int) -> str:
    """Truncates text to max_len with ellipsis if it exceeds the limit."""
    if not text or max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[:max_len - 3] + "..."

async def safe_delete_message(message: discord.Message | None):
    if not message:
        return
    try:
        await message.delete()
    except Exception:
        pass

async def safe_fetch_message(channel, message_id: int | None):
    if not message_id:
        return None
    try:
        return await channel.fetch_message(message_id)
    except Exception:
        return None
