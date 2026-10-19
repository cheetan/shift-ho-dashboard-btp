from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re

EET = ZoneInfo("Europe/Bucharest")

SHIFT_HOURS = {
    "night":   (0,  8),
    "morning": (8,  16),
    "evening": (16, 24),
}
SHIFT_ICONS = {"morning": "🌅", "evening": "🌆", "night": "🌙"}
SHIFT_ORDER = ["night", "morning", "evening"]


def detect_shift(now_eet=None):
    if now_eet is None:
        now_eet = datetime.now(EET)
    h = now_eet.hour
    if h < 8:  return "night"
    if h < 16: return "morning"
    return "evening"


def get_shift_window(shift_name, now_eet=None):
    if now_eet is None:
        now_eet = datetime.now(EET)
    today = now_eet.date()
    start_h, end_h = SHIFT_HOURS[shift_name]
    start_dt = datetime(today.year, today.month, today.day, start_h, 0, tzinfo=EET)
    if end_h == 24:
        end_dt = datetime(today.year, today.month, today.day, 0, 0, tzinfo=EET) + timedelta(days=1)
    else:
        end_dt = datetime(today.year, today.month, today.day, end_h, 0, tzinfo=EET)
    label = (f"{SHIFT_ICONS[shift_name]} {shift_name.capitalize()} Shift — "
             f"{today.strftime('%d %b %Y')}  "
             f"{start_h:02d}:00 – {end_h % 24:02d}:00 EET")
    return label, start_dt.strftime("%Y-%m-%d %H:%M"), end_dt.strftime("%Y-%m-%d %H:%M")


def get_previous_shift_window(shift_name, now_eet=None):
    if now_eet is None:
        now_eet = datetime.now(EET)
    idx = SHIFT_ORDER.index(shift_name)
    prev_name = SHIFT_ORDER[(idx - 1) % 3]
    ref = now_eet - timedelta(days=1) if shift_name == "night" else now_eet
    return get_shift_window(prev_name, ref)


def get_next_shift_window(shift_name, now_eet=None):
    if now_eet is None:
        now_eet = datetime.now(EET)
    idx = SHIFT_ORDER.index(shift_name)
    next_name = SHIFT_ORDER[(idx + 1) % 3]
    ref = now_eet + timedelta(days=1) if shift_name == "evening" else now_eet
    return get_shift_window(next_name, ref)


def parse_spc_subject_dt(subject, ref_year=None):
    if ref_year is None:
        ref_year = datetime.now().year
    m = re.search(r'(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\s+(\d{2}):(\d{2})\s+UTC', subject)
    if not m:
        return None
    try:
        from datetime import timezone
        year = int(m.group(3)) if m.group(3) else ref_year
        return datetime(year, int(m.group(2)), int(m.group(1)),
                        int(m.group(4)), int(m.group(5)), tzinfo=timezone.utc)
    except ValueError:
        return None
