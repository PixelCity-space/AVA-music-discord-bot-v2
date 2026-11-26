from abc import ABC, abstractmethod
from typing import Any


class MusicProvider(ABC):
    @abstractmethod
    async def resolve(self, query: str) -> dict[str, Any] | None:
        """
        Resolves a search query or URL into a standardized song dictionary.
        Returns None if resolution fails.
        """

    @abstractmethod
    def matches(self, query: str) -> bool:
        """
        Returns True if this provider can handle the given query/URL.
        """

    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """
        Searches for tracks based on a query.
        """
    @abstractmethod
    def is_playlist(self, query: str) -> bool:
        """
        Returns True if the query/URL refers to a playlist.
        """
