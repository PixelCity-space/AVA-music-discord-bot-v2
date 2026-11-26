from enum import Enum, auto

from core.models import Song


class RadioState(Enum):
    IDLE = auto()
    PLAYING = auto()
    PAUSED = auto()
    STOPPED = auto()
    BUFFERING = auto()

class RadioAction(Enum):
    JOIN = auto()
    DISCONNECT = auto()
    PAUSE = auto()
    STOP = auto()
    SKIP = auto()
    SEEK = auto()
    REPLAY = auto()
    SET_VOLUME = auto()
    BACK = auto()
    ADD_EXT_LINK = auto()
    ADD_SONGS = auto()
    
    # Queue Management
    REMOVE_FROM_QUEUE = auto()
    CLEAR_QUEUE = auto()
    MOVE_SONG = auto() # Used for both UP/DOWN
    
    # Favorites & History
    TOGGLE_FAVORITE = auto()
    CLEAR_FAVORITES = auto()
    CLEAR_HISTORY = auto()
    
    # Modes
    LOOP = auto()
    LOOP_QUEUE = auto()
    SHUFFLE = auto()
    RESTART = auto()
    CLEAR_CACHE = auto()

# Type hint for all valid action payload types dispatched to RadioManager / PlaybackActionHandler
RadioActionData = (
    str                               # ADD_EXT_LINK (URL/query), SEEK timestamp string
    | int                             # JOIN (channel_id), SEEK (seconds)
    | float                           # SET_VOLUME (fraction 0.0 - 1.0)
    | Song                            # REMOVE_FROM_QUEUE
    | list[Song]                      # ADD_SONGS
    | tuple[Song, int]                # MOVE_SONG (song, direction)
    | tuple[int | str, Song]          # TOGGLE_FAVORITE (user_id, song)
    | None
)
