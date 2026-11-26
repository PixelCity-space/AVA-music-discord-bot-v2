from discord.ui import ActionRow, Container, Separator, TextDisplay

from ui.components.list_controls import (
    AddAllFavoritesButton,
    ClearFavoritesButton,
    FavoriteRemoveButton,
    SearchResultAddButton,
)
from ui.feedback import get_feedback
from ui.theme import Theme
from ui.utils import format_duration, truncate
from ui.views.base import PaginatedView


class FavoritesView(PaginatedView):
    def __init__(self, radio, user_id: str | int, page: int = 0, data_list=None):
        favs = data_list if data_list is not None else radio.fav_manager.get_favorites(user_id)
        super().__init__(radio, favs, items_per_page=radio.config.search_items_per_page, page=page)
        self.user_id = user_id
        
        container = Container(accent_color=Theme.PRIMARY)
        container.add_item(TextDisplay(f"### {get_feedback('library_label')}"))
        container.add_item(Separator())
        
        if not favs:
            container.add_item(TextDisplay(f"*{get_feedback('empty')}*"))
        else:
            items = self.get_page_items()
            for i, song in enumerate(items, self.current_page * self.items_per_page + 1):
                t_title = truncate(song.title or get_feedback('unknown'), radio.config.list_max_title_len)
                info = f"**{i}. {t_title}** ({format_duration(song.duration)})"
                container.add_item(TextDisplay(info))
                
                row = ActionRow()
                row.add_item(SearchResultAddButton(radio, song))
                row.add_item(FavoriteRemoveButton(radio, song))
                container.add_item(row)
                
        container.add_item(Separator())
        container.add_item(TextDisplay(self.pagination_info))
        
        extra_btns = [AddAllFavoritesButton(radio, favs), ClearFavoritesButton(radio, self.user_id)] if favs else []
        container.add_item(self.build_navigation_row(extra_buttons=extra_btns))
        
        self.add_item(container)

    async def refresh_view(self, interaction, reload: bool = True):
        cached_list = None if reload else self.data_list
        new_view = FavoritesView(self.radio, self.user_id, page=self.current_page, data_list=cached_list)
        await interaction.edit_original_response(view=new_view)

    async def paginate_refresh(self, interaction) -> None:
        await self.refresh_view(interaction, reload=False)
