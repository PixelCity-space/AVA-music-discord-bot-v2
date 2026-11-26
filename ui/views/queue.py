from typing import Optional
from discord.ui import ActionRow, Container, TextDisplay, Separator
from ui.theme import Theme
from ui.feedback import get_feedback
from ui.utils import format_duration, truncate
from ui.views.base import PaginatedView
from ui.components.list_controls import (
    MoveUpButton, 
    MoveDownButton, 
    RemoveFromQueueButton, 
    FavoriteListButton, 
    ClearQueueButton
)
from core.models import Song

class FullQueueView(PaginatedView):
    def __init__(self, radio, page: int = 0, user: Optional[object] = None):
        queue = [Song.from_dict(r) if isinstance(r, dict) else r for r in radio.queue]
        super().__init__(radio, queue, items_per_page=radio.config.queue_items_per_page, page=page)
        self.user = user
        container = Container(accent_color=Theme.PRIMARY)
        container.add_item(TextDisplay(f"### {get_feedback('queue_label')}"))
        container.add_item(Separator())
        
        if not self.data_list:
            container.add_item(TextDisplay(f"*{get_feedback('empty')}*"))
        else:
            items = self.get_page_items()
            for i, song in enumerate(items, self.current_page * self.items_per_page + 1):
                raw_title = song.title or get_feedback('unknown')
                t_title = truncate(raw_title, radio.config.list_max_title_len)
                song_info = f"**{i}. {t_title}** ({format_duration(song.duration)})"
                container.add_item(TextDisplay(song_info))
                
                row = ActionRow()
                is_first = (i == 1)
                is_last = (i == len(radio.queue))
                row.add_item(MoveUpButton(radio, song, is_first=is_first))
                row.add_item(MoveDownButton(radio, song, is_last=is_last))
                row.add_item(RemoveFromQueueButton(radio, song))
                row.add_item(FavoriteListButton(radio, song, user_id=self.user.id if self.user else None))
                container.add_item(row)
                
        container.add_item(TextDisplay(self.pagination_info))
        container.add_item(self.build_navigation_row(extra_buttons=[ClearQueueButton(radio)]))
        self.add_item(container)

    async def refresh_view(self, interaction):
        new_view = FullQueueView(self.radio, page=self.current_page, user=self.user)
        await interaction.edit_original_response(view=new_view)
