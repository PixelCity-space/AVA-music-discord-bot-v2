import json
import os
import re
from ui.icons import Icons

_translations_cache = {}
_resolved_cache: dict[tuple[str, str, int], dict] = {}
_radio_ref = None
_ICON_PATTERN = re.compile(r"\{([A-Z0-9_]+)\}")


def _resolve_icons_in_text(text: str) -> str:
    if "{" not in text:
        return text
    return _ICON_PATTERN.sub(
        lambda m: str(getattr(Icons, m.group(1))) if hasattr(Icons, m.group(1)) else m.group(0),
        text,
    )


def load_locales_for_instance(instance_name: str = "") -> dict:
    """Load all base .json files and apply instance-specific overrides."""
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    locales_path = os.path.join(root_dir, "locales")

    trans = {}
    if not os.path.exists(locales_path):
        return trans

    # 1. Base languages (e.g. hu.json, en.json)
    for filename in os.listdir(locales_path):
        if filename.endswith(".json") and "_" not in filename:
            lang_code = filename[:-5]
            try:
                with open(os.path.join(locales_path, filename), "r", encoding="utf-8") as f:
                    trans[lang_code] = json.load(f)
            except Exception as e:
                print(f"Error loading base locale {filename}: {e}")

    # 2. Instance-specific overrides (e.g. hu_1.json, hu_2.json)
    inst = instance_name or os.environ.get("INSTANCE_NAME", "")
    if inst:
        for filename in os.listdir(locales_path):
            if filename.endswith(f"_{inst}.json"):
                lang_code = filename.split("_")[0]
                if lang_code in trans:
                    try:
                        with open(os.path.join(locales_path, filename), "r", encoding="utf-8") as f:
                            overrides = json.load(f)
                            trans[lang_code].update(overrides)
                    except Exception as e:
                        print(f"Error loading instance override {filename}: {e}")
    return trans


def load_locales(instance_name: str = "") -> dict:
    return load_locales_for_instance(instance_name)


def get_translations(instance_name: str = "") -> dict:
    inst = instance_name or os.environ.get("INSTANCE_NAME", "")
    if inst not in _translations_cache:
        _translations_cache[inst] = load_locales_for_instance(inst)
    return _translations_cache[inst]


def _get_resolved_lang_dict(inst: str, lang: str) -> dict:
    cache_key = (inst, lang, Icons._version)
    cached = _resolved_cache.get(cache_key)
    if cached is not None:
        return cached

    trans_map = get_translations(inst)
    raw_dict = trans_map.get(lang, trans_map.get("en", {}))
    en_dict = trans_map.get("en", {})

    resolved = {}
    # Merge fallback English keys first, then target language keys, with icons pre-substituted
    for k, v in en_dict.items():
        resolved[k] = _resolve_icons_in_text(v) if isinstance(v, str) else v
    for k, v in raw_dict.items():
        resolved[k] = _resolve_icons_in_text(v) if isinstance(v, str) else v

    if len(_resolved_cache) > 32:
        _resolved_cache.clear()
    _resolved_cache[cache_key] = resolved
    return resolved


def init_translate(radio_instance):
    global _radio_ref
    _radio_ref = radio_instance
    inst = getattr(radio_instance, "instance_name", "")
    _translations_cache[inst] = load_locales_for_instance(inst)
    _resolved_cache.clear()


def t(key: str, radio=None, **kwargs) -> str:
    """
    Translates a key based on the current radio language and instance.
    Uses pre-resolved icon placeholders cached per language and icon version.
    """
    r = radio or _radio_ref
    inst = getattr(r, "instance_name", "") if r else os.environ.get("INSTANCE_NAME", "")
    lang = getattr(r, "language", "hu") if r else "hu"

    lang_dict = _get_resolved_lang_dict(inst, lang)
    text = lang_dict.get(key, key)

    if kwargs and isinstance(text, str):
        try:
            text = text.format(**kwargs)
        except Exception:
            pass

    return text
