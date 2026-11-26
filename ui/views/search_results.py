from discord.ui import ActionRow, Container, Separator, TextDisplay

from core.models import Song
from ui.components.list_controls import FavoriteListButton, SearchResultAddButton
from ui.feedback import get_feedback
from ui.i18n import t
from ui.theme import Theme
from ui.utils import format_duration, truncate
from ui.views.base import PaginatedView


class SearchResultsView(PaginatedView):
    def __init__(self, radio, results, query=None, user=None, page=0):
        results = [Song.from_dict(r) if isinstance(r, dict) else r for r in results]
        super().__init__(radio, results, items_per_page=radio.config.search_items_per_page, page=page)
        self.results = results
        self.query = query
        self.user = user
        
        container = Container(accent_color=Theme.PRIMARY)
        
        header_text = f"### {get_feedback('search_results_title')}"
        if query:
            header_text += f" - *\"{query}\"*"
        if user:
            header_text += f" ({user.name})"
            
        container.add_item(TextDisplay(header_text))
        container.add_item(Separator())

        items = self.get_page_items()
        for i, res in enumerate(items, self.current_page * self.items_per_page + 1):
            t_title = truncate(res.title or get_feedback('unknown'), radio.config.list_max_title_len)
            info = f"**{i}. {t_title}** ({format_duration(res.duration)})"
            container.add_item(TextDisplay(info))
            
            row = ActionRow()
            row.add_item(SearchResultAddButton(radio, res))
            row.add_item(FavoriteListButton(radio, res, user_id=self.user.id if self.user else None))
            container.add_item(row)
            
        container.add_item(Separator())
        container.add_item(TextDisplay(f"{t('results_label')}: {len(results)} | {self.pagination_info}"))
        container.add_item(self.build_navigation_row())
        
        self.add_item(container)

    async def refresh_view(self, interaction):
        new_view = SearchResultsView(
            self.radio, 
            self.results, 
            query=self.query, 
            user=self.user, 
            page=self.current_page
        )
        await interaction.edit_original_response(view=new_view)
