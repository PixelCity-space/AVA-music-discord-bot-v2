import json
import os

class EmbedStateManager:
    def __init__(self, filename: str | None = None, instance_name: str = ""):
        inst = instance_name or os.getenv("INSTANCE_NAME", "")
        if filename is None:
            filename = f"data/{inst}_embed_state.json" if inst else "data/embed_state.json"
            
        self.path = os.path.abspath(filename)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.state = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, default=str)
        except Exception:
            pass

    def save_message_id(self, key: str, message_id: int | None):
        state_key = f"msg_{key}"
        if message_id is None:
            if state_key in self.state:
                del self.state[state_key]
                self.save()
            return
        if not isinstance(message_id, int) or message_id <= 0:
            return
        if self.state.get(state_key) == message_id:
            return
        self.state[state_key] = message_id
        self.save()

    def clear_message_ids(self, *keys: str):
        changed = False
        for key in keys:
            state_key = f"msg_{key}"
            if state_key in self.state:
                del self.state[state_key]
                changed = True
        if changed:
            self.save()

    def load_message_id(self, key: str):
        return self.state.get(f"msg_{key}")

    def save_value(self, key: str, value):
        self.state[key] = value
        self.save()

    def load_value(self, key: str, default=None):
        return self.state.get(key, default)
