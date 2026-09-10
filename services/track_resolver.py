import ipaddress
import os
import re
from urllib.parse import urlparse
from typing import Optional, List
import discord
from core.models import Song
from core.database import Database
from providers import resolve_any, resolve_playlist_any
from utils.logger import log

class TrackResolverService:
    """
    Dedicated service for resolving audio tracks, search queries, and playlists from providers.
    Handles caching resolved metadata and updating song state.
    """
    MAX_QUERY_LEN = 500
    ALLOWED_SCHEMES = {"http", "https"}

    def __init__(self, db: Database, providers: list):
        self.db = db
        self.providers = providers

    @classmethod
    def sanitize_query(cls, query: str) -> Optional[str]:
        """
        Sanitizes and validates user input query or URL.
        Rejects queries exceeding length limit, forbidden URL schemes, control chars, or injection patterns.
        """
        if not query:
            return None

        # Remove control chars (null bytes, newlines, tabs)
        cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", query).strip()
        if not cleaned or len(cleaned) > cls.MAX_QUERY_LEN:
            log.warning(f"[SECURITY] Query rejected: empty or exceeds {cls.MAX_QUERY_LEN} chars.")
            return None

        # If it starts with a scheme or looks like a URL, enforce strict whitelist
        if "://" in cleaned:
            parsed = urlparse(cleaned)
            if parsed.scheme.lower() not in cls.ALLOWED_SCHEMES:
                log.warning(f"[SECURITY] Disallowed URL scheme in query: {parsed.scheme}")
                return None
            
            hostname = (parsed.hostname or "").lower()
            if not hostname:
                log.warning(f"[SECURITY] Invalid URL host in query: {cleaned}")
                return None

            # Reject localhost, single-label local hostnames, or loopback identifiers
            if hostname in {"localhost", "0.0.0.0", "::1"} or "." not in hostname:
                log.warning(f"[SECURITY] Disallowed local/private host in query: {hostname}")
                return None

            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    log.warning(f"[SECURITY] Disallowed private/reserved IP host in query: {hostname}")
                    return None
            except ValueError:
                # Regular domain name with dot(s)
                pass

        return cleaned

    def is_matching_provider(self, query: str):
        """Returns the matching provider for a given URL query, if any."""
        return next((p for p in self.providers if p.matches(query)), None)

    async def prepare_external_song(self, query: str, user: Optional[discord.Member | discord.User] = None) -> Optional[Song]:
        """Prepares a Song object from a URL or search query with cache lookup."""
        query = self.sanitize_query(query)
        if not query:
            return None

        provider = self.is_matching_provider(query)

        if provider:
            cached = self.db.get_cache(query)
            if cached:
                song = Song.from_dict(cached)
                song.path = query
                log.info(f"[CACHE] Hit for: {query}")
                if cached.get("local_path") and os.path.exists(cached["local_path"]):
                    song.is_resolving = False
                else:
                    song.is_resolving = True
            else:
                song = Song(
                    title=None,
                    path=query,
                    uploader="...",
                    duration=0,
                    is_external=True,
                    is_resolving=True
                )
        else:
            log.info(f"[SEARCH] Searching for: {query}")
            search_results = []
            for p in self.providers:
                if hasattr(p, 'search'):
                    res = await p.search(query, limit=1)
                    if res:
                        search_results.extend(res)
            
            if not search_results:
                log.warning(f"[SEARCH] No results found for: {query}")
                return None
            
            song = Song.from_dict(search_results[0])
            song.is_resolving = False
            log.info(f"[SEARCH] Added first result: {song.title}")

        if user:
            song.user_id = str(user.id)
            song.requested_by = user.display_name

        return song

    async def resolve_playlist(self, url: str, user: Optional[discord.Member | discord.User] = None) -> List[Song]:
        """Resolves all tracks within a playlist URL."""
        tracks_data = await resolve_playlist_any(url, self.providers)
        if not tracks_data:
            log.warning(f"[RESOLVER] Failed to resolve playlist: {url}")
            return []

        log.info(f"[RESOLVER] Playlist resolved: {len(tracks_data)} tracks found.")
        songs = []
        for data in tracks_data:
            song = Song.from_dict(data)
            song.is_resolving = False
            if user:
                song.user_id = str(user.id)
                song.requested_by = user.display_name
            songs.append(song)

        # Atomic bulk cache insertion
        self.db.set_cache_batch(tracks_data)
        return songs

    async def resolve_song(self, song: Song) -> bool:
        """Resolves metadata for a single Song asynchronously."""
        try:
            resolved = await resolve_any(song.path, self.providers)
            if resolved:
                song.update(resolved)
                cached = self.db.get_cache(song.path)
                song.cache_to_db(self.db, local_path=cached.get("local_path") if cached else None)
                log.info(f"[RESOLVER] Successfully resolved: {song.uploader} - {song.title}")
                return True
            else:
                song.title = f"⚠️ {song.path}"
                log.warning(f"[RESOLVER] Failed to resolve link: {song.path}")
                return False
        except Exception as e:
            log.error(f"[RADIO] Resolution task exception: {e}")
            song.title = f"⚠️ {song.path}"
            return False
        finally:
            song.is_resolving = False
            song.resolve_event.set()
