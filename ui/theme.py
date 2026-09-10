
class Theme:
    PRIMARY = 0x2b2d31
    SECONDARY = 0x2b2d31
    SUCCESS = 0x57F287
    WARNING = 0xFEE75C
    DANGER = 0xED4245
    BACKGROUND = 0x2b2d31
    ACCENT = 0xEB459E
    PLAYING = 0x1c6bff
    PAUSED = 0xFEE75C
    STOPPED = 0xED4245
    IDLE = 0x2b2d31
    BUFFERING = 0xEB459E

    @classmethod
    def init_theme(cls, config):
        theme_data = config.ui_settings.get("theme", {}) if hasattr(config, "ui_settings") else {}

        def parse_color(key: str, default: int) -> int:
            val = theme_data.get(key)
            if val is None:
                return default
            try:
                if isinstance(val, int):
                    return val
                return int(str(val), 16)
            except Exception:
                return default

        cls.PRIMARY = parse_color("primary", 0x2b2d31)
        cls.SECONDARY = parse_color("secondary", 0x2b2d31)
        cls.SUCCESS = parse_color("success", 0x57F287)
        cls.WARNING = parse_color("warning", 0xFEE75C)
        cls.DANGER = parse_color("danger", 0xED4245)
        cls.BACKGROUND = parse_color("background", 0x2b2d31)
        cls.ACCENT = parse_color("accent", 0xEB459E)
        cls.PLAYING = parse_color("playing", 0x1c6bff)
        cls.PAUSED = parse_color("paused", 0xFEE75C)
        cls.STOPPED = parse_color("stopped", 0xED4245)
        cls.IDLE = parse_color("idle", 0x2b2d31)
        cls.BUFFERING = parse_color("buffering", 0xEB459E)
