import os
import time
import glob
import hashlib
import asyncio
import shutil
import sys
from typing import Optional, Callable
from core.models import Song
from core.database import Database
from utils.logger import log

COMMON_AUDIO_EXTS = (".opus", ".webm", ".m4a", ".mp3", ".ogg", ".mp4", ".wav")


class CacheService:
    DOWNLOAD_TIMEOUT_SECONDS = 120.0
    MAX_CONCURRENT_DOWNLOADS = 2

    def __init__(self, config, database: Database):
        self.config = config
        self.db = database
        self.cache_dir = os.path.join(os.getcwd(), "data", "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._download_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_DOWNLOADS)
        self._url_locks: dict[str, asyncio.Lock] = {}
        self._in_flight: set[str] = set()
        self._path_index: dict[str, str] = {}
        self._ytdlp_cmd = self._resolve_ytdlp_cmd()

    def _resolve_ytdlp_cmd(self) -> list[str]:
        """Resolves and caches executable command for yt-dlp on Linux and Windows."""
        ytdlp = getattr(self.config, 'ytdlp_path', 'yt-dlp')
        if isinstance(ytdlp, str) and ytdlp and shutil.which(ytdlp):
            return [ytdlp]
        return [sys.executable, "-m", "yt_dlp"]

    def _get_ytdlp_cmd(self) -> list[str]:
        """Returns cached executable command for yt-dlp."""
        return self._ytdlp_cmd

    @staticmethod
    def _hash_path(path: str) -> str:
        return hashlib.sha1(path.encode()).hexdigest()

    def get_cache_path(self, song: Song) -> Optional[str]:
        """Returns the local file path if a cached file exists for this song."""
        if not song or not song.path:
            return None
        fn_hash = self._hash_path(song.path)

        indexed = self._path_index.get(fn_hash)
        if indexed and os.path.exists(indexed):
            return indexed

        for ext in COMMON_AUDIO_EXTS:
            candidate = os.path.join(self.cache_dir, f"{fn_hash}{ext}")
            if os.path.exists(candidate):
                self._path_index[fn_hash] = candidate
                return candidate

        matches = glob.glob(os.path.join(self.cache_dir, f"{fn_hash}.*"))
        if matches:
            self._path_index[fn_hash] = matches[0]
            return matches[0]
        return None

    def is_cached(self, song: Song) -> bool:
        """Returns True if a valid local file exists for this song."""
        if not song or not song.path:
            return False

        # Check DB first for stored local path
        cached_data = self.db.get_cache(song.path)
        if cached_data:
            if song.title == song.path or (song.title and "[" in song.title):
                song.title = cached_data.get("title", song.title)
                song.uploader = cached_data.get("uploader", song.uploader)
                song.duration = cached_data.get("duration", song.duration)
                song.thumbnail_url = cached_data.get("thumbnail_url", song.thumbnail_url)

            lp = cached_data.get("local_path")
            if lp and os.path.exists(lp):
                self._path_index[self._hash_path(song.path)] = lp
                return True

        # Fallback: Check deterministic path with known extensions
        lp = self.get_cache_path(song)
        if lp and os.path.exists(lp):
            song.cache_to_db(self.db, local_path=lp)
            return True

        return False

    async def start_cache_download(self, song: Song, task_creator: Optional[Callable] = None):
        """Initiates a background download of the song to the local cache without duplicate tasks."""
        if not song or not song.path or song.path in self._in_flight or self.is_cached(song):
            return

        self._in_flight.add(song.path)
        coro = self._download_task(song)
        if task_creator:
            task_creator(coro, name=f"cache_dl_{self._hash_path(song.path)[:8]}")
        else:
            asyncio.create_task(coro)

    async def _download_task(self, song: Song):
        url_key = song.path
        lock = self._url_locks.setdefault(url_key, asyncio.Lock())
        process = None
        try:
            async with lock:
                if self.is_cached(song):
                    return

                async with self._download_semaphore:
                    if self.is_cached(song):
                        return

                    fn_hash = self._hash_path(song.path)
                    target_path_template = os.path.join(self.cache_dir, f"{fn_hash}.%(ext)s")
                    log.info(f"[CACHE] Starting download: {song.title}")

                    cmd = [
                        *self._get_ytdlp_cmd(),
                        "-f", "bestaudio/best",
                        "--no-playlist",
                        "--no-check-certificates",
                        "--no-update",
                        "--extractor-args", "youtube:player_client=android,web",
                        "-o", target_path_template,
                        song.path
                    ]

                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.DOWNLOAD_TIMEOUT_SECONDS
                    )

                    if process.returncode == 0:
                        actual_path = self.get_cache_path(song)
                        if actual_path:
                            log.info(f"[CACHE] Download complete: {song.title} -> {actual_path}")
                            song.cache_to_db(self.db, local_path=actual_path)
                    else:
                        err = stderr.decode(errors="ignore").strip()
                        log.error(f"[CACHE] Download failed for {song.title}: {err}")
        except asyncio.TimeoutError:
            log.error(f"[CACHE] Download timed out for {song.title}. Killing process.")
            if process:
                try:
                    process.kill()
                except Exception:
                    pass
        except Exception as e:
            log.error(f"[CACHE] Download exception for {song.title}: {e}")
        finally:
            self._in_flight.discard(url_key)
            if not lock.locked():
                self._url_locks.pop(url_key, None)

    async def cleanup_cache_async(self):
        """Runs cache cleanup off the asyncio event loop."""
        await asyncio.to_thread(self.cleanup_cache)

    def cleanup_cache(self):
        """Auto-cleanup of the cache based on size and expiry."""
        try:
            files = []
            with os.scandir(self.cache_dir) as entries:
                for entry in entries:
                    if entry.is_file():
                        stats = entry.stat()
                        files.append({
                            "path": entry.path,
                            "size": stats.st_size,
                            "atime": stats.st_atime
                        })

            if not files:
                return

            files.sort(key=lambda x: x["atime"])

            now = time.time()
            expiry_seconds = self.config.cache_expiry_days * 86400
            size_limit = self.config.max_cache_size_mb * 1024 * 1024

            total_size = sum(f["size"] for f in files)
            deleted_count = 0

            # 1. Expiry cleanup
            remaining_files = []
            for f in files:
                if (now - f["atime"]) > expiry_seconds:
                    try:
                        os.remove(f["path"])
                        total_size -= f["size"]
                        deleted_count += 1
                    except Exception as e:
                        log.warning(f"[CACHE] Could not delete expired file {f['path']}: {e}")
                        remaining_files.append(f)
                else:
                    remaining_files.append(f)

            # 2. Size cleanup (LRU)
            for f in remaining_files:
                if total_size <= size_limit:
                    break
                try:
                    os.remove(f["path"])
                    total_size -= f["size"]
                    deleted_count += 1
                except Exception as e:
                    log.warning(f"[CACHE] Could not delete LRU file {f['path']}: {e}")

            if deleted_count > 0:
                self._path_index.clear()
                log.info(f"[CACHE] Auto-cleanup: {deleted_count} files removed.")

        except Exception as e:
            log.error(f"[CACHE] Auto-cleanup error: {e}")

    def clear_cache(self) -> int:
        """Deletes all files in the cache directory."""
        try:
            count = 0
            with os.scandir(self.cache_dir) as entries:
                for entry in entries:
                    if entry.is_file():
                        os.remove(entry.path)
                        count += 1

            self._path_index.clear()
            self.db.clear_cache()
            log.info(f"[CACHE] Manual cache clear: {count} files removed.")
            return count
        except Exception as e:
            log.error(f"[CACHE] Error clearing cache: {e}")
            return 0

    def delete_cache_file(self, song: Song):
        """Deletes the local cache file for a specific song (ephemeral cache)."""
        if not song or not song.path:
            return

        path = self.get_cache_path(song)
        self._path_index.pop(self._hash_path(song.path), None)
        if path and os.path.exists(path):
            try:
                os.remove(path)
                log.info(f"[CACHE] Ephemeral deletion: {song.title}")
                song.cache_to_db(self.db, local_path=None)
            except Exception as e:
                log.warning(f"[CACHE] Could not delete ephemeral file {path}: {e}")
