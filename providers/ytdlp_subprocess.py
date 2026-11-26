import asyncio
import asyncio.subprocess
import json
from typing import Any

from utils.logger import log


class YTDLPSubprocessBackend:
    """CLI subprocess fallback transport for yt-dlp probing, playlists, and search."""

    def __init__(self, exec_cmd: list[str], common_args: list[str]):
        self.exec_cmd = exec_cmd
        self.common_args = common_args

    async def _run_json_lines(
        self,
        args: list[str],
        timeout: float,
        label: str,
        target: str,
        ignore_non_zero: bool = False,
    ) -> list[dict[str, Any]] | None:
        process = None
        try:
            cmd = [*self.exec_cmd, *args, *self.common_args, target]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

            if process.returncode != 0 and not ignore_non_zero:
                err_msg = stderr.decode(errors="ignore").strip()
                log.error(f"[YT-DLP] Error {label} {target} (code {process.returncode}): {err_msg}")
                return None

            items: list[dict[str, Any]] = []
            if stdout:
                for line in stdout.decode().splitlines():
                    if not line.strip():
                        continue
                    items.append(json.loads(line))
            return items
        except TimeoutError:
            log.error(f"[YT-DLP] {label} timed out for {target}. Killing process.")
            if process:
                try:
                    process.kill()
                except Exception as kill_err:
                    log.debug(f"[YT-DLP] Failed to kill timed-out subprocess: {kill_err}")
            return None
        except Exception as e:
            log.error(f"[YT-DLP] Exception {label} {target}: {e}", exc_info=True)
            return None

    async def extract_single(self, target: str) -> dict[str, Any] | None:
        referer = "https://soundcloud.com/" if "soundcloud.com" in target else "https://www.google.com"
        items = await self._run_json_lines(
            ["-j", "-f", "bestaudio[ext=mp3]/bestaudio/best", "--no-playlist", "--referer", referer],
            timeout=20.0,
            label="probing",
            target=target,
        )
        return items[0] if items else None

    async def extract_playlist(self, url: str) -> list[dict[str, Any]]:
        referer = "https://soundcloud.com/" if "soundcloud.com" in url else "https://www.google.com"
        items = await self._run_json_lines(
            ["-j", "--flat-playlist", "--referer", referer],
            timeout=30.0,
            label="fetching playlist",
            target=url,
        )
        return items or []

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        items = await self._run_json_lines(
            ["-j", "--flat-playlist", "--no-playlist", "--print-json"],
            timeout=15.0,
            label="searching",
            target=f"ytsearch{limit}:{query}",
            ignore_non_zero=True,
        )
        return items or []

