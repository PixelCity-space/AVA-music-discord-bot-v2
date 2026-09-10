import asyncio
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

@dataclass
class Song:
    path: str  # The playback URL or file path
    title: Optional[str] = None
    uploader: Optional[str] = None
    duration: int = 0
    thumbnail_url: Optional[str] = None
    webpage_url: Optional[str] = None
    source: Optional[str] = None
    requested_by: Optional[str] = None  # Mention string or name
    user_id: Optional[str] = None       # Snowflake ID for stats
    played_at: Optional[str] = None     # Timestamp when it was played
    
    # Internal state
    is_resolving: bool = False
    is_external: bool = False
    stream_url: Optional[str] = None
    http_headers: Optional[Dict[str, str]] = None
    _resolve_event: Optional[asyncio.Event] = field(default=None, repr=False, compare=False)

    @property
    def resolve_event(self) -> asyncio.Event:
        if self._resolve_event is None:
            self._resolve_event = asyncio.Event()
            if not self.is_resolving:
                self._resolve_event.set()
        return self._resolve_event

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Song":
        """Factory method to create a Song object from a dictionary."""
        uploader = data.get("uploader") or data.get("artist") or data.get("channel")
        
        return cls(
            title=data.get("title"),
            path=data.get("path") or data.get("url", ""),
            uploader=uploader,
            duration=max(0, int(data.get("duration") or 0)),
            thumbnail_url=data.get("thumbnail_url") or data.get("thumbnail"),
            webpage_url=data.get("webpage_url"),
            source=data.get("source"),
            requested_by=data.get("requested_by"),
            user_id=data.get("user_id"),
            is_resolving=data.get("is_resolving", False),
            is_external=data.get("is_external", False),
            stream_url=data.get("stream_url"),
            http_headers=data.get("http_headers"),
            played_at=data.get("played_at")
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert back to dict."""
        d = dict(self.__dict__)
        d.pop("_resolve_event", None)
        return d
    
    def update(self, data: Dict[str, Any]):
        """Update fields from a dictionary with priority mapping."""
        # 1. Direct field mapping
        for key, value in data.items():
            if hasattr(self, key) and value is not None and key != "_resolve_event":
                current = getattr(self, key)
                is_placeholder = False
                if isinstance(current, str):
                    is_placeholder = current in ["...", ""] or (current.startswith("[") and "]" in current)
                
                if current in [None, 0] or is_placeholder or self.is_resolving or key == "stream_url":
                    setattr(self, key, value)

        # 2. Logic-based mapping for uploader
        new_uploader = data.get("uploader") or data.get("artist") or data.get("channel")
        if new_uploader and (self.uploader in [None, "...", ""]):
            self.uploader = new_uploader
        
        # 3. Path/URL mapping
        new_path = data.get("path") or data.get("url")
        if new_path and (self.path in [None, ""]):
            self.path = new_path

        if not self.is_resolving and self._resolve_event is not None:
            self._resolve_event.set()

    def cache_to_db(self, db, local_path: Optional[str] = None):
        """Persists the song metadata to SQLite cache using the provided Database instance."""
        if not self.path or not self.path.strip() or not db:
            return
        db.set_cache(
            url=self.path,
            title=self.title or "",
            uploader=self.uploader or "Unknown",
            duration=self.duration,
            thumbnail_url=self.thumbnail_url or "",
            local_path=local_path
        )
