"""
Prefix-based text command dispatcher and handlers using Command Registry Pattern.
"""

import asyncio
import discord
from ui.views.player import HelpView
from ui.views.queue import FullQueueView
from ui.utils import get_feedback
from utils.logger import log


# --- Command Handler Functions ---

async def _cmd_play(ctx):
    query = " ".join(ctx["args"]).strip() if ctx["args"] else None
    res = ctx["cs"].play(ctx["author"], query)
    await ctx["chan"].send(f"{ctx['author'].mention} {res.feedback}", delete_after=ctx["timeout"])

async def _cmd_stop(ctx):
    res = ctx["cs"].stop(ctx["author"])
    await ctx["chan"].send(f"{ctx['author'].mention} {res.feedback}", delete_after=ctx["timeout"])

async def _cmd_disconnect(ctx):
    res = ctx["cs"].disconnect(ctx["author"])
    await ctx["chan"].send(f"{ctx['author'].mention} {res.feedback}", delete_after=ctx["timeout"])

async def _cmd_skip(ctx):
    res = ctx["cs"].skip(ctx["author"])
    await ctx["chan"].send(f"{ctx['author'].mention} {res.feedback}", delete_after=ctx["timeout"])

async def _cmd_back(ctx):
    res = ctx["cs"].back(ctx["author"])
    await ctx["chan"].send(f"{ctx['author'].mention} {res.feedback}", delete_after=ctx["timeout"])

async def _cmd_join(ctx):
    res = ctx["cs"].join(ctx["author"])
    await ctx["chan"].send(f"{ctx['author'].mention} {res.feedback}", delete_after=ctx["timeout"])

async def _cmd_volume(ctx):
    if not ctx["args"]:
        return
    try:
        vol = int(ctx["args"][0])
        res = ctx["cs"].volume(ctx["author"], vol)
        await ctx["chan"].send(f"{ctx['author'].mention} {res.feedback}", delete_after=ctx["timeout"])
    except Exception:
        await ctx["chan"].send(f"{ctx['author'].mention} {get_feedback('invalid_number')}", delete_after=ctx["timeout"])

async def _cmd_loop(ctx):
    res = ctx["cs"].loop(ctx["author"])
    await ctx["chan"].send(f"{ctx['author'].mention} {res.feedback}", delete_after=ctx["timeout"])

async def _cmd_loop_queue(ctx):
    res = ctx["cs"].loop_queue(ctx["author"])
    await ctx["chan"].send(f"{ctx['author'].mention} {res.feedback}", delete_after=ctx["timeout"])

async def _cmd_shuffle(ctx):
    res = ctx["cs"].shuffle(ctx["author"])
    await ctx["chan"].send(f"{ctx['author'].mention} {res.feedback}", delete_after=ctx["timeout"])

async def _cmd_queue(ctx):
    if not ctx["radio"].can_interact(ctx["author"]):
        await ctx["chan"].send(f"{ctx['author'].mention} {get_feedback('not_in_same_voice')}", delete_after=ctx["timeout"])
        return
    view = FullQueueView(ctx["radio"], page=0, user=ctx["author"])
    await ctx["chan"].send(view=view, delete_after=ctx["config"].view_timeout)

async def _cmd_help(ctx):
    view = HelpView(ctx["radio"])
    await ctx["chan"].send(embed=view.get_embed(), delete_after=ctx["config"].view_timeout)

async def _cmd_restart(ctx):
    res = ctx["cs"].restart(ctx["author"])
    await ctx["chan"].send(f"{ctx['author'].mention} {res.feedback}", delete_after=ctx["timeout"])

async def _cmd_clearcache(ctx):
    res = ctx["cs"].clear_cache(ctx["author"])
    await ctx["chan"].send(f"{ctx['author'].mention} {res.feedback}", delete_after=ctx["timeout"])

async def _cmd_seek(ctx):
    if not ctx["args"]:
        await ctx["chan"].send(f"{ctx['author'].mention} {get_feedback('format_error')}", delete_after=ctx["timeout"])
        return
    res = ctx["cs"].seek(ctx["author"], ctx["args"][0])
    await ctx["chan"].send(f"{ctx['author'].mention} {res.feedback}", delete_after=ctx["timeout"])


# --- Command Registry (alias -> handler) ---

COMMAND_REGISTRY = {
    "play": _cmd_play, "p": _cmd_play,
    "stop": _cmd_stop,
    "disconnect": _cmd_disconnect, "leave": _cmd_disconnect, "d": _cmd_disconnect, "l": _cmd_disconnect,
    "skip": _cmd_skip, "s": _cmd_skip,
    "back": _cmd_back, "b": _cmd_back,
    "join": _cmd_join, "j": _cmd_join,
    "volume": _cmd_volume, "v": _cmd_volume,
    "loop": _cmd_loop, "lt": _cmd_loop,
    "loopq": _cmd_loop_queue, "lq": _cmd_loop_queue,
    "shuffle": _cmd_shuffle, "sh": _cmd_shuffle,
    "queue": _cmd_queue, "q": _cmd_queue,
    "help": _cmd_help, "h": _cmd_help,
    "restart": _cmd_restart,
    "clearcache": _cmd_clearcache,
    "seek": _cmd_seek,
}


# --- Entry Point ---

async def handle_prefix_commands(message: discord.Message, radio):
    """Processes traditional prefix commands using a dispatch registry."""
    if message.author.bot or not message.content:
        return

    config = radio.config
    if message.channel.id != config.radio_text_channel_id:
        return

    prefix = config.command_prefix
    clean_content = message.content.strip()
    if not clean_content.startswith(prefix):
        return

    content = clean_content[len(prefix):].strip()
    if not content:
        return

    parts = content.split()
    command = parts[0].lower()
    args = parts[1:]

    handler = COMMAND_REGISTRY.get(command)
    if not handler:
        return

    async def delayed_delete(msg):
        await asyncio.sleep(config.command_delete_delay)
        try:
            await msg.delete()
        except discord.Forbidden:
            log.warning(f"Could not delete message from {msg.author}: Missing 'Manage Messages' permission.")
        except Exception:
            pass

    try:
        asyncio.create_task(delayed_delete(message))
        ctx = {
            "cs": radio.command_service,
            "radio": radio,
            "config": config,
            "author": message.author,
            "chan": message.channel,
            "timeout": config.notification_timeout,
            "args": args,
        }
        await handler(ctx)
    except Exception as e:
        log.error(f"Error in prefix command {command}: {e}")
