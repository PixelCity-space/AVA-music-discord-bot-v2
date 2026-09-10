import asyncio
import asyncio.subprocess
import json
import shutil
import sys
from typing import Optional, Dict, Any, List
from .base import MusicProvider
from utils.logger import log

class YTDLPProvider(MusicProvider):
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"

    def __init__(self, ytdlp_path: str = "yt-dlp", user_agent: Optional[str] = None):
        self.ytdlp_path = ytdlp_path
        ua = user_agent or self.DEFAULT_USER_AGENT
        self.common_args = [
            "--socket-timeout", "10",
            "--no-warnings",
            "--ignore-errors",
            "--no-check-certificates",
            "--no-update",
            "--extractor-args", "youtube:player_client=android,web",
            "--user-agent", ua
        ]

    def _get_exec_cmd(self) -> List[str]:
        """Returns the appropriate command list to run yt-dlp across Linux and Windows."""
        if shutil.which(self.ytdlp_path):
            return [self.ytdlp_path]
        return [sys.executable, "-m", "yt_dlp"]

    def matches(self, query: str) -> bool:
        return query.startswith(("http://", "https://", "www."))

    async def resolve(self, url: str) -> Optional[Dict[str, Any]]:
        return await self._resolve_internal(url, playlist=False)

    def is_playlist(self, query: str) -> bool:
        return "list=" in query or "playlist" in query.lower() or "/sets/" in query.lower()

    async def _resolve_internal(self, url: str, playlist: bool = False) -> Optional[Dict[str, Any]]:
        process = None
        try:
            referer = "https://soundcloud.com/" if "soundcloud.com" in url else "https://www.google.com"
            cmd = [
                *self._get_exec_cmd(), 
                "-j", 
                "-f", "bestaudio[ext=mp3]/bestaudio/best",
                "--no-playlist",
                "--referer", referer,
                *self.common_args,
                url
            ]
                 
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20.0)
            
            if process.returncode != 0:
                err_msg = stderr.decode(errors="ignore").strip()
                log.error(f"[YT-DLP] Error probing {url} (code {process.returncode}): {err_msg}")
                return None
                
            info = json.loads(stdout.decode())
            
            stream_url = info.get("url")
            if not stream_url and "formats" in info:
                formats = info["formats"]
                audio_formats = [f for f in formats if f.get("vcodec") == "none"]
                if audio_formats:
                    stream_url = audio_formats[-1].get("url")
                else:
                    stream_url = formats[-1].get("url")
            
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
                "path": url
            }
        except asyncio.TimeoutError:
            log.error(f"[YT-DLP] Resolution timed out for {url}. Killing process.")
            if process:
                try:
                    process.kill()
                except Exception:
                    pass
            return None
        except Exception as e:
            log.error(f"[YT-DLP] Exception resolving {url}: {e}")
            return None

    async def resolve_playlist(self, url: str) -> List[Dict[str, Any]]:
        process = None
        try:
            referer = "https://soundcloud.com/" if "soundcloud.com" in url else "https://www.google.com"
            cmd = [
                *self._get_exec_cmd(), 
                "-j", 
                "--flat-playlist",
                "--referer", referer,
                *self.common_args,
                url
            ]
                 
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
            
            if process.returncode != 0:
                err_msg = stderr.decode(errors="ignore").strip()
                log.error(f"[YT-DLP] Error fetching playlist {url}: {err_msg}")
                return []
                
            results = []
            lines = stdout.decode().splitlines()
            for line in lines:
                try:
                    info = json.loads(line)
                    results.append({
                        "title": info.get("title", "Unknown Title"),
                        "uploader": info.get("uploader") or info.get("channel") or info.get("artist") or "Unknown Artist",
                        "duration": max(0, int(info.get("duration") or 0)),
                        "path": info.get("url") or info.get("webpage_url"),
                        "thumbnail_url": info.get("thumbnail"),
                        "is_external": True,
                        "webpage_url": info.get("webpage_url") or (f"https://www.youtube.com/watch?v={info['id']}" if info.get('id') else None)
                    })
                except Exception:
                    continue
            return results
        except asyncio.TimeoutError:
            log.error(f"[YT-DLP] Playlist fetch timed out for {url}. Killing process.")
            if process:
                try:
                    process.kill()
                except Exception:
                    pass
            return []
        except Exception as e:
            log.error(f"[YT-DLP] Playlist resolution exception for {url}: {e}")
            return []

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        process = None
        try:
            search_query = f"ytsearch{limit}:{query}"
            cmd = [
                *self._get_exec_cmd(), 
                "-j", 
                "--flat-playlist",
                "--no-playlist",
                "--print-json",
                *self.common_args,
                search_query
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15.0)
            
            results = []
            if stdout:
                lines = stdout.decode().splitlines()
                for line in lines:
                    try:
                        info = json.loads(line)
                        results.append({
                            "title": info.get("title", "Unknown"),
                            "uploader": info.get("uploader") or info.get("channel") or "Unknown",
                            "duration": max(0, int(info.get("duration") or 0)),
                            "path": info.get("url") or info.get("webpage_url"),
                            "thumbnail_url": info.get("thumbnail"),
                            "is_external": True
                        })
                    except Exception:
                        continue
            return results
        except asyncio.TimeoutError:
            log.error(f"[YT-DLP] Search timed out for query '{query}'. Killing process.")
            if process:
                try:
                    process.kill()
                except Exception:
                    pass
            return []
        except Exception as e:
            log.error(f"[YT-DLP] Search exception for {query}: {e}")
            return []
