import discord
import traceback
from discord.ui import LayoutView
from ui.icons import Icons
from ui.i18n import t
from ui.utils import get_feedback, delayed_delete
from utils.logger import log
import asyncio

def handle_ui_error(func):
    """Decorator to handle errors in UI callbacks and enforce permissions."""
    async def wrapper(*args, **kwargs):
        interaction = next((arg for arg in args if isinstance(arg, discord.Interaction)), None)
        if not interaction:
            return await func(*args, **kwargs)

        # Ignore interactions on messages authored by another bot instance
        if interaction.message and interaction.client and interaction.client.user:
            if interaction.message.author.id != interaction.client.user.id:
                return

        self_obj = args[0] if args else None
        radio = getattr(self_obj, 'radio', None)
        
        if radio and hasattr(radio, 'can_interact'):
            if not radio.can_interact(interaction.user):
                feedback = get_feedback('not_in_same_voice')
                if not interaction.response.is_done():
                    await interaction.response.send_message(feedback, ephemeral=True)
                else:
                    await interaction.followup.send(feedback, ephemeral=True)
                
                asyncio.create_task(delayed_delete(interaction, radio.config.notification_timeout))
                return

        try:
            return await func(*args, **kwargs)
        except (discord.errors.NotFound, discord.errors.HTTPException) as e:
            code = getattr(e, 'code', 0)
            if code in [10062, 40060]: 
                return
            
            log.error(f"UI Error in {func.__name__}: {e}")
            await _send_error_msg(interaction)
        except Exception as e:
            log.error(f"UI Error in {func.__name__}: {e}")
            traceback.print_exc()
            await _send_error_msg(interaction)
    return wrapper

async def _send_error_msg(interaction):
    if not interaction:
        return
    feedback = get_feedback('error_generic')
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(feedback, ephemeral=True)
        else:
            await interaction.followup.send(feedback, ephemeral=True)
    except Exception:
        pass

class BaseView(LayoutView):
    """Base class for all Radio Bot views with shared logic."""

    def __init__(self, radio, timeout=None):
        super().__init__(timeout=timeout)
        self.radio = radio

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        log.error(f"View Error: {error} in {item}")
        traceback.print_exc()
        feedback = get_feedback('error_generic')
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(feedback, ephemeral=True)
            else:
                await interaction.followup.send(feedback, ephemeral=True)
        except discord.errors.NotFound:
            log.warning(f"Could not send view error message (interaction expired): {error}")
        except Exception as e:
            log.error(f"Error in View.on_error: {e}")

class PaginatedView(BaseView):
    """Base class for views requiring pagination."""

    def __init__(self, radio, data_list, items_per_page=5, timeout=None, page=0):
        super().__init__(radio, timeout=timeout)
        self.data_list = data_list
        self.items_per_page = items_per_page
        self.total_pages = max(1, (len(data_list) + items_per_page - 1) // items_per_page)
        self.current_page = max(0, min(page, self.total_pages - 1))

    def get_page_items(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        return self.data_list[start:end]

    def update_pagination_buttons(self, prev_button, next_button):
        """Helper to update state of Prev/Next buttons."""
        if prev_button:
            prev_button.disabled = (self.current_page == 0)
        if next_button:
            next_button.disabled = (self.current_page >= self.total_pages - 1)

    @property
    def pagination_info(self):
        return f"{t('page')} {self.current_page + 1} / {self.total_pages} ({len(self.data_list)} {t('total')})"

    async def refresh_view(self, interaction: discord.Interaction):
        """Should be overridden by subclasses to update the message with a new view instance."""
        raise NotImplementedError

    def build_navigation_row(self, extra_buttons: list | None = None, show_close: bool = True) -> discord.ui.ActionRow:
        """Constructs a standard pagination ActionRow with Prev, Next, optional custom buttons, and Close."""
        nav = discord.ui.ActionRow()
        
        prev_btn = discord.ui.Button(
            emoji=Icons.PREV, 
            style=discord.ButtonStyle.secondary, 
            disabled=(self.current_page == 0)
        )
        next_btn = discord.ui.Button(
            emoji=Icons.NEXT, 
            style=discord.ButtonStyle.secondary, 
            disabled=(self.current_page >= self.total_pages - 1)
        )

        @handle_ui_error
        async def prev_cb(interaction: discord.Interaction):
            await interaction.response.defer()
            self.current_page -= 1
            await self.refresh_view(interaction)

        @handle_ui_error
        async def next_cb(interaction: discord.Interaction):
            await interaction.response.defer()
            self.current_page += 1
            await self.refresh_view(interaction)

        prev_btn.callback = prev_cb
        next_btn.callback = next_cb

        nav.add_item(prev_btn)
        nav.add_item(next_btn)

        if extra_buttons:
            for btn in extra_buttons:
                nav.add_item(btn)

        if show_close:
            close_btn = discord.ui.Button(emoji=Icons.CLOSE, style=discord.ButtonStyle.danger)

            @handle_ui_error
            async def close_cb(interaction: discord.Interaction):
                await interaction.response.defer()
                await interaction.delete_original_response()

            close_btn.callback = close_cb
            nav.add_item(close_btn)

        return nav
