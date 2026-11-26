from ui.components.progress_bar import create_progress_bar
from ui.feedback import get_feedback
from ui.utils import format_duration, truncate
from ui.icons import Icons

def test_progress_bar_zero_or_negative_total(test_radio):
    bar = create_progress_bar(current=0, total=0, width=18)
    assert bar.startswith(str(Icons.PB_START))
    assert bar.endswith(str(Icons.PB_RIGHT))

    bar_neg = create_progress_bar(current=10, total=-5, width=18)
    assert bar_neg.startswith(str(Icons.PB_START))

def test_progress_bar_start_position(test_radio):
    bar = create_progress_bar(current=0, total=100, width=18)
    assert str(Icons.PB_START) in bar
    assert str(Icons.PB_RIGHT) in bar

def test_progress_bar_middle_position(test_radio):
    bar = create_progress_bar(current=50, total=100, width=18)
    assert str(Icons.PB_KNOB) in bar
    assert str(Icons.PB_FULL) in bar
    assert str(Icons.PB_EMPTY) in bar

def test_progress_bar_completed(test_radio):
    bar = create_progress_bar(current=100, total=100, width=18)
    assert str(Icons.PB_END) in bar
    assert str(Icons.PB_LEFT) in bar

def test_progress_bar_clamped_over_100(test_radio):
    bar = create_progress_bar(current=150, total=100, width=18)
    assert str(Icons.PB_END) in bar

def test_format_duration_zero():
    assert format_duration(0) == "0:00"

def test_format_duration_seconds():
    assert format_duration(45) == "0:45"

def test_format_duration_minutes():
    assert format_duration(125) == "2:05"

def test_format_duration_hours():
    assert format_duration(3665) == "61:05"

def test_truncate_empty():
    assert truncate("", 10) == ""
    assert truncate(None, 10) == ""

def test_truncate_short_text():
    assert truncate("Hello", 10) == "Hello"

def test_truncate_exact_length():
    assert truncate("0123456789", 10) == "0123456789"

def test_truncate_exceeding_length():
    assert truncate("A very long title here", 10) == "A very ..."
    assert len(truncate("A very long title here", 10)) <= 10

def test_get_feedback_with_icon(test_radio):
    fb = get_feedback("no_permission")
    assert str(Icons.ERROR) in fb

def test_get_feedback_warning(test_radio):
    fb = get_feedback("not_in_same_voice")
    assert str(Icons.WARNING) in fb

def test_get_feedback_success(test_radio):
    fb = get_feedback("weblink_added")
    assert str(Icons.SUCCESS) in fb
