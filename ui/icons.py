import discord


class Icons:
    _version: int = 0
    SUCCESS: discord.PartialEmoji
    ADD: discord.PartialEmoji
    BACK: discord.PartialEmoji
    GEAR: discord.PartialEmoji
    ERROR: discord.PartialEmoji
    CLOSE: discord.PartialEmoji
    DISCONNECT: discord.PartialEmoji
    FOLDER_HEART: discord.PartialEmoji
    GLOBE: discord.PartialEmoji
    HEADPHONES: discord.PartialEmoji
    HEART_MINUS: discord.PartialEmoji
    HEART_PLUS: discord.PartialEmoji
    HELP: discord.PartialEmoji
    HISTORY: discord.PartialEmoji
    IDLE: discord.PartialEmoji
    MOVE_DOWN: discord.PartialEmoji
    MOVE_UP: discord.PartialEmoji
    NEXT: discord.PartialEmoji
    PAUSE: discord.PartialEmoji
    PLAY: discord.PartialEmoji
    PREV: discord.PartialEmoji
    QUEUE: discord.PartialEmoji
    RADIO: discord.PartialEmoji
    REMOVE: discord.PartialEmoji
    SEARCH: discord.PartialEmoji
    SEEK: discord.PartialEmoji
    SKIP: discord.PartialEmoji
    STANDBY: discord.PartialEmoji
    STOP: discord.PartialEmoji
    SWEEP: discord.PartialEmoji
    SYNC: discord.PartialEmoji
    VOLUME: discord.PartialEmoji
    WARNING: discord.PartialEmoji
    BUFFERING: discord.PartialEmoji
    REPEAT: discord.PartialEmoji

    PB_START: discord.PartialEmoji
    PB_LEFT: discord.PartialEmoji
    PB_FULL: discord.PartialEmoji
    PB_KNOB: discord.PartialEmoji
    PB_EMPTY: discord.PartialEmoji
    PB_RIGHT: discord.PartialEmoji
    PB_END: discord.PartialEmoji

    @classmethod
    def setup(cls, config):
        """Initializes all icons from config or hardcoded defaults."""
        defaults = {
            "SUCCESS": "✅", "GEAR": "⚙️", "RADIO": "📻", "HELP": "❓", "SWEEP": "🧹",
            "MOVE_DOWN": "🔽", "PREV": "◀️", "NEXT": "▶️", "MOVE_UP": "🔼", "SEEK": "⏩",
            "FOLDER_HEART": "📂", "GLOBE": "🌐", "HEADPHONES": "🎧",
            "HEART_MINUS": "💔", "HEART_PLUS": "❤️", "IDLE": "🌙", "SYNC": "🔄",
            "PAUSE": "⏸️", "PLAY": "▶️", "ADD": "➕", "QUEUE": "📑", "HISTORY": "📜",
            "SEARCH": "🔍", "BACK": "⏮️", "SKIP": "⏭️", "STOP": "⏹️", "STANDBY": "⏳",
            "BUFFERING": "⏳", "REMOVE": "🗑️", "WARNING": "⚠️", "DISCONNECT": "🔌",
            "VOLUME": "🔊", "REPEAT": "🔁", "CLOSE": "❌", "ERROR": "❌",
            "PB_START": "[", "PB_LEFT": "█", "PB_FULL": "█", "PB_KNOB": "🔘",
            "PB_EMPTY": "░", "PB_RIGHT": "]", "PB_END": "]"
        }

        provided_data = config.emojis if hasattr(config, "emojis") else {}
        
        def get(name):
            val = provided_data.get(name)
            if not val:
                val = defaults.get(name, "❓")
            return discord.PartialEmoji.from_str(val)

        cls.SUCCESS = get("SUCCESS")
        cls.ADD = get("ADD")
        cls.BACK = get("BACK")
        cls.GEAR = get("GEAR")
        cls.ERROR = get("ERROR")
        cls.CLOSE = get("CLOSE")
        cls.DISCONNECT = get("DISCONNECT")
        cls.FOLDER_HEART = get("FOLDER_HEART")
        cls.GLOBE = get("GLOBE")
        cls.HEADPHONES = get("HEADPHONES")
        cls.HEART_MINUS = get("HEART_MINUS")
        cls.HEART_PLUS = get("HEART_PLUS")
        cls.HELP = get("HELP")
        cls.HISTORY = get("HISTORY")
        cls.IDLE = get("IDLE")
        cls.MOVE_DOWN = get("MOVE_DOWN")
        cls.MOVE_UP = get("MOVE_UP")
        cls.NEXT = get("NEXT")
        cls.PAUSE = get("PAUSE")
        cls.PLAY = get("PLAY")
        cls.PREV = get("PREV")
        cls.QUEUE = get("QUEUE")
        cls.RADIO = get("RADIO")
        cls.REMOVE = get("REMOVE")
        cls.SEARCH = get("SEARCH")
        cls.SEEK = get("SEEK")
        cls.SKIP = get("SKIP")
        cls.STANDBY = get("STANDBY")
        cls.STOP = get("STOP")
        cls.SWEEP = get("SWEEP")
        cls.SYNC = get("SYNC")
        cls.VOLUME = get("VOLUME")
        cls.WARNING = get("WARNING")
        cls.REPEAT = get("REPEAT")
        cls.BUFFERING = get("BUFFERING")
        
        cls.PB_START = get("PB_START")
        cls.PB_LEFT = get("PB_LEFT")
        cls.PB_FULL = get("PB_FULL")
        cls.PB_KNOB = get("PB_KNOB")
        cls.PB_EMPTY = get("PB_EMPTY")
        cls.PB_RIGHT = get("PB_RIGHT")
        cls.PB_END = get("PB_END")
        cls._version += 1

class DefaultConfig:
    emojis = {}

Icons.setup(DefaultConfig())
