import asyncio
import json
import os
import threading

from utils.logger import log


class EmbedStateManager:
    def __init__(self, filename: str | None = None, instance_name: str = ""):
        inst = instance_name or os.getenv("INSTANCE_NAME", "")
        if filename is None:
            filename = f"data/{inst}_embed_state.json" if inst else "data/embed_state.json"

        self.path = os.path.abspath(filename)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._io_lock = threading.Lock()
        self.state = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log.warning(f"[EMBED_STATE] Failed to load '{self.path}', starting with empty state: {e}")
        return {}

    def save(self):
        with self._io_lock:
            payload = dict(self.state)
            try:
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, default=str)
            except Exception as e:
                log.error(f"[EMBED_STATE] Failed to save '{self.path}': {e}", exc_info=True)

    async def save_async(self):
        """Persists embed state off the asyncio event loop."""
        await asyncio.to_thread(self.save)

    def _apply_message_id(self, key: str, message_id: int | None) -> bool:
        state_key = f"msg_{key}"
        if message_id is None:
            if state_key in self.state:
                del self.state[state_key]
                return True
            return False
        if not isinstance(message_id, int) or message_id <= 0:
            return False
        if self.state.get(state_key) == message_id:
            return False
        self.state[state_key] = message_id
        return True

    def save_message_id(self, key: str, message_id: int | None):
        if self._apply_message_id(key, message_id):
            self.save()

    async def save_message_id_async(self, key: str, message_id: int | None):
        if self._apply_message_id(key, message_id):
            await self.save_async()

    def _apply_clear_message_ids(self, *keys: str) -> bool:
        changed = False
        for key in keys:
            state_key = f"msg_{key}"
            if state_key in self.state:
                del self.state[state_key]
                changed = True
        return changed

    def clear_message_ids(self, *keys: str):
        if self._apply_clear_message_ids(*keys):
            self.save()

    async def clear_message_ids_async(self, *keys: str):
        if self._apply_clear_message_ids(*keys):
            await self.save_async()

    def load_message_id(self, key: str):
        return self.state.get(f"msg_{key}")

    def save_value(self, key: str, value):
        self.state[key] = value
        self.save()

    def load_value(self, key: str, default=None):
        return self.state.get(key, default)
