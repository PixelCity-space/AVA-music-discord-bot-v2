import asyncio
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from providers.base import MusicProvider
from providers.ytdlp_subprocess import YTDLPSubprocessBackend
from utils.logger import log

try:
    import yt_dlp
except ImportError:  # pragma: no cover
    yt_dlp = None


class YTDLPProvider(MusicProvider):
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"

    def __init__(self, ytdlp_path: str = "yt-dlp", user_agent: Optional[str] = None, use_subprocess: Optional[bool] = None):
        self.ytdlp_path = ytdlp_path
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        self._executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="ytdlp")
        self._exec_cmd = self._resolve_exec_cmd()

        if use_subprocess is not None:
            self._use_subprocess = use_subprocess
        else:
            self._use_subprocess = (yt_dlp is None) or (ytdlp_path not in ("yt-dlp", "", None))

        self.common_args = [
            "--socket-timeout", "10",
            "--no-warnings",
            "--ignore-errors",
            "--no-check-certificates",
            "--no-update",
            "--extractor-args", "youtube:player_client=android,web",
            "--user-agent", self.user_agent,
        ]
        self._subprocess_backend = YTDLPSubprocessBackend(self._exec_cmd, self.common_args)

    def _resolve_exec_cmd(self) -> List[str]:
        """Resolves and caches the executable command to run yt-dlp across Linux and Windows."""
        if self.ytdlp_path and shutil.which(self.ytdlp_path):
            return [self.ytdlp_path]
        return [sys.executable, "-m", "yt_dlp"]

    def _get_exec_cmd(self) -> List[str]:
        """Returns the cached command list to run yt-dlp."""
        return self._exec_cmd

    def close(self):
        """Shuts down the thread pool executor cleanly."""
        self._executor.shutdown(wait=False)

    def matches(self, query: str) -> bool:
        return query.startswith(("http://", "https://", "www."))

    def is_playlist(self, query: str) -> bool:
        return "list=" in query or "playlist" in query.lower() or "/sets/" in query.lower()

    def _build_ydl_opts(self, referer: str, extra_opts: Dict[str, Any]) -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "socket_timeout": 10,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            "http_headers": {
                "User-Agent": self.user_agent,
                "Referer": referer,
            },
        }
        opts.update(extra_opts)
        return opts

    @staticmethod
    def _extract_stream_url(info: Dict[str, Any]) -> Optional[str]:
        stream_url = info.get("url")
        if not stream_url and "formats" in info:
            formats = info["formats"] or []
            audio_formats = [f for f in formats if f.get("vcodec") == "none"]
            if audio_formats:
                stream_url = audio_formats[-1].get("url")
            elif formats:
                stream_url = formats[-1].get("url")
        return stream_url

    @classmethod
    def _normalize_resolved(cls, info: Optional[Dict[str, Any]], url: str) -> Optional[Dict[str, Any]]:
        if not info:
            return None
        if "entries" in info:
            entries = [e for e in (info.get("entries") or []) if e]
            if not entries:
                return None
            info = entries[0]

        stream_url = cls._extract_stream_url(info)
        if not stream_url:
            log.warning(f"[YT-DLP] No stream URL found in metadata for {url}")
            return None

        return {
            "title": info.get("title", "Unknown Title"),
            "uploader": info.get("uploader") or info.get("channel") or info.get("artist") or "Unknown Artist",
            "album": info.get("extractor_key", "Web Stream"),
            "duration": max(0, int(info.get("duration") or 0)),
            "stream_url": stream_url,
            "thumbnail_url": info.get("thumbnail"),
            "http_headers": info.get("http_headers", {}),
            "is_external": True,
            "webpage_url": info.get("webpage_url"),
            "path": url,
        }

    @staticmethod
    def _normalize_playlist_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "title": entry.get("title", "Unknown Title"),
            "uploader": entry.get("uploader") or entry.get("channel") or entry.get("artist") or "Unknown Artist",
            "duration": max(0, int(entry.get("duration") or 0)),
            "path": entry.get("url") or entry.get("webpage_url"),
            "thumbnail_url": entry.get("thumbnail"),
            "is_external": True,
            "webpage_url": entry.get("webpage_url") or (f"https://www.youtube.com/watch?v={entry['id']}" if entry.get("id") else None),
        }

    @staticmethod
    def _normalize_search_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "title": entry.get("title", "Unknown"),
            "uploader": entry.get("uploader") or entry.get("channel") or "Unknown",
            "duration": max(0, int(entry.get("duration") or 0)),
            "path": entry.get("url") or entry.get("webpage_url"),
            "thumbnail_url": entry.get("thumbnail"),
            "is_external": True,
        }

    def _extract_info_sync(self, target: str, ydl_opts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(target, download=False)

    async def _run_in_executor(self, target: str, opts: Dict[str, Any], timeout: float, label: str) -> Optional[Dict[str, Any]]:
        try:
            loop = asyncio.get_running_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(self._executor, self._extract_info_sync, target, opts),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            log.error(f"[YT-DLP] {label} timed out for {target}.")
            return None
        except Exception as e:
            log.error(f"[YT-DLP] Exception {label} {target}: {e}", exc_info=True)
            return None

    async def resolve(self, url: str) -> Optional[Dict[str, Any]]:
        if not self._use_subprocess and yt_dlp is not None:
            referer = "https://soundcloud.com/" if "soundcloud.com" in url else "https://www.google.com"
            opts = self._build_ydl_opts(referer, {
                "format": "bestaudio[ext=mp3]/bestaudio/best",
                "noplaylist": True,
                "ignoreerrors": False,
            })
            info = await self._run_in_executor(url, opts, timeout=20.0, label="resolving")
            return self._normalize_resolved(info, url)

        raw = await self._subprocess_backend.extract_single(url)
        return self._normalize_resolved(raw, url)

    async def resolve_playlist(self, url: str) -> List[Dict[str, Any]]:
        if not self._use_subprocess and yt_dlp is not None:
            referer = "https://soundcloud.com/" if "soundcloud.com" in url else "https://www.google.com"
            opts = self._build_ydl_opts(referer, {
                "extract_flat": "in_playlist",
                "ignoreerrors": True,
            })
            info = await self._run_in_executor(url, opts, timeout=30.0, label="resolving playlist")
            raw_entries = (info.get("entries") or []) if info else []
            entries = [e for e in raw_entries if e]
            if info is None or not entries:
                log.debug(f"[YT-DLP] Playlist returned 0 usable entries for {url}")
            elif len(entries) < len(raw_entries):
                log.debug(f"[YT-DLP] Filtered {len(raw_entries) - len(entries)} unavailable playlist entries for {url}")
        else:
            entries = await self._subprocess_backend.extract_playlist(url)

        return [self._normalize_playlist_entry(e) for e in entries]

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not self._use_subprocess and yt_dlp is not None:
            search_query = f"ytsearch{limit}:{query}"
            opts = self._build_ydl_opts("https://www.google.com", {
                "extract_flat": True,
                "noplaylist": True,
                "ignoreerrors": True,
            })
            info = await self._run_in_executor(search_query, opts, timeout=15.0, label="searching")
            raw_entries = (info.get("entries") or []) if info else []
            entries = [e for e in raw_entries if e]
            if not entries:
                log.debug(f"[YT-DLP] Search returned 0 entries for query '{query}'")
        else:
            entries = await self._subprocess_backend.search(query, limit=limit)

        return [self._normalize_search_entry(e) for e in entries]

    async def search_and_resolve_first(self, query: str) -> Optional[Dict[str, Any]]:
        """Resolves metadata and stream_url for the top search result in a single yt-dlp request."""
        resolved = await self.resolve(f"ytsearch1:{query}")
        if resolved:
            resolved["path"] = resolved.get("webpage_url") or resolved.get("path")
        return resolved
