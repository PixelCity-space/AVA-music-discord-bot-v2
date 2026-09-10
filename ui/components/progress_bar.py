"""
Progress bar visual component generating text and emoji-based visual seekbars.
"""

from ui.icons import Icons

def create_progress_bar(current: int, total: int, width: int = 18) -> str:
    """Generates a text/emoji-based progress bar."""
    if width <= 0:
        return ""
    if width == 1:
        return str(Icons.PB_START if (current <= 0 or total <= 0) else Icons.PB_END)
    if total <= 0:
        return f"{Icons.PB_START}{str(Icons.PB_EMPTY) * (width - 2)}{Icons.PB_RIGHT}"
    
    progress = min(1.0, max(0.0, current / total))
    filled_count = int(progress * (width - 1))
    
    parts = []
    for i in range(width):
        if i == 0:
            parts.append(Icons.PB_START if filled_count == 0 else Icons.PB_LEFT)
        elif i == width - 1:
            parts.append(Icons.PB_END if progress >= 1.0 else Icons.PB_RIGHT)
        elif i == filled_count:
            parts.append(Icons.PB_KNOB)
        elif i < filled_count:
            parts.append(Icons.PB_FULL)
        else:
            parts.append(Icons.PB_EMPTY)
    
    return "".join(map(str, parts))
