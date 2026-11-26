import asyncio
from typing import Any

import discord

from utils.logger import log

_pending_delete_tasks: set[asyncio.Task] = set()


def schedule_delete(item: discord.Message | discord.Interaction | None, delay: float = 20.0) -> asyncio.Task | None:
    """Schedules delayed_delete while retaining a strong task reference until completion."""
    if not item:
        return None
    task = asyncio.create_task(delayed_delete(item, delay))
    _pending_delete_tasks.add(task)

    def _on_done(t: asyncio.Task):
        _pending_delete_tasks.discard(t)
        if not t.cancelled():
            exc = t.exception()
            if exc:
                log.error(f"[UI] Unhandled error in scheduled delete task: {exc}", exc_info=exc)

    task.add_done_callback(_on_done)
    return task


async def delayed_delete(item: discord.Message | discord.Interaction | None, delay: float = 20.0):
    if not item:
        return
    
    await asyncio.sleep(delay)
    try:
        if isinstance(item, discord.Interaction):
            await item.delete_original_response()
        elif isinstance(item, discord.Message):
            await item.delete()
    except discord.NotFound:
        pass
    except discord.Forbidden as e:
        log.warning(f"[UI] Missing permission to delete message/interaction: {e}")
    except Exception as e:
        log.debug(f"[UI] Delayed delete failed: {e}")

async def respond(interaction: discord.Interaction, content=None, embed=None, view=None, ephemeral=True, delete_after: float | None = None):
    """
    Modularized interaction responder. 
    Handles both initial response and followup automatically.
    If delete_after is provided, the message will be scheduled for deletion.
    """
    kwargs: dict[str, Any] = {"ephemeral": ephemeral}
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
            schedule_delete(target, delete_after)
    except Exception as e:
        user_name = getattr(getattr(interaction, "user", None), "name", "unknown")
        cmd_name = getattr(getattr(interaction, "command", None), "name", None)
        custom_id = (getattr(interaction, "data", None) or {}).get("custom_id") if isinstance(getattr(interaction, "data", None), dict) else None
        log.error(f"UI Respond error (user={user_name}, target={cmd_name or custom_id or 'unknown'}): {e}", exc_info=True)

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
    except discord.NotFound:
        pass
    except discord.Forbidden as e:
        log.warning(f"[UI] Missing permission to delete message {getattr(message, 'id', '?')}: {e}")
    except Exception as e:
        log.debug(f"[UI] Failed to delete message {getattr(message, 'id', '?')}: {e}")

async def safe_fetch_message(channel, message_id: int | None):
    if not message_id:
        return None
    try:
        return await channel.fetch_message(message_id)
    except discord.NotFound:
        return None
    except discord.Forbidden as e:
        log.warning(f"[UI] Missing permission to fetch message {message_id}: {e}")
        return None
    except Exception as e:
        log.debug(f"[UI] Failed to fetch message {message_id}: {e}")
        return None
