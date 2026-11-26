from discord.ui import ActionRow, Container, Separator, TextDisplay

from core.models import Song
from ui.components.list_controls import (
    ClearHistoryButton,
    FavoriteListButton,
    SearchResultAddButton,
)
from ui.feedback import get_feedback
from ui.theme import Theme
from ui.utils import format_duration, truncate
from ui.views.base import PaginatedView


class HistoryView(PaginatedView):
    def __init__(self, radio, page: int = 0, user=None, data_list=None):
        if data_list is not None:
            history = data_list
        else:
            history = [Song.from_dict(r) if isinstance(r, dict) else r for r in radio.history]
        super().__init__(radio, history, items_per_page=radio.config.search_items_per_page, page=page)
        self.radio = radio
        self.user = user
        
        container = Container(accent_color=Theme.PRIMARY)
        container.add_item(TextDisplay(f"### {get_feedback('history_label')}"))
        container.add_item(Separator())
        
        if not history:
            container.add_item(TextDisplay(f"*{get_feedback('no_prev_track')}*"))
        else:
            items = self.get_page_items()
            for i, song in enumerate(items, self.current_page * self.items_per_page + 1):
                t_title = truncate(song.title or get_feedback('unknown'), radio.config.list_max_title_len)
                t_user = song.requested_by or get_feedback('unknown')
                t_played = song.played_at or ""
                
                info = f"**{i}. {t_title}** ({format_duration(song.duration)})\n*{t_played} - {t_user}*"
                container.add_item(TextDisplay(info))
                
                row = ActionRow()
                row.add_item(SearchResultAddButton(radio, song))
                row.add_item(FavoriteListButton(radio, song, user_id=self.user.id if self.user else None))
                container.add_item(row)
                
        container.add_item(Separator())
        container.add_item(TextDisplay(self.pagination_info))
        
        extra_btns = [ClearHistoryButton(radio)] if (user and radio.is_admin(user)) else []
        container.add_item(self.build_navigation_row(extra_buttons=extra_btns))
        
        self.add_item(container)

    async def refresh_view(self, interaction, reload: bool = True):
        cached_list = None if reload else self.data_list
        new_view = HistoryView(self.radio, page=self.current_page, user=self.user, data_list=cached_list)
        await interaction.edit_original_response(view=new_view)

    async def paginate_refresh(self, interaction) -> None:
        await self.refresh_view(interaction, reload=False)
