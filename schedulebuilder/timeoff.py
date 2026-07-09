"""Hardcoded PGY-4 time-off requests (transcribed from data/timeoff.csv), keyed by
the resident's last name (matching schedulebuilder.roster.LAST_NAME)."""

import datetime as dt

TIME_OFF_REQUESTS = {
    "D'Amore": [
        (dt.date(2026, 9, 26), dt.date(2026, 9, 28)),
        (dt.date(2026, 10, 5), dt.date(2026, 10, 8)),
    ],
    "Malits": [
        (dt.date(2026, 9, 20), dt.date(2026, 9, 21)),
    ],
    "Botticelli": [
        (dt.date(2026, 10, 31), dt.date(2026, 11, 1)),
    ],
    "Okonkwo": [
        (dt.date(2026, 11, 11), dt.date(2026, 11, 15)),
    ],
    "Shoaib": [
        (dt.date(2026, 11, 3), dt.date(2026, 11, 3)),
        (dt.date(2026, 10, 17), dt.date(2026, 10, 18)),
        (dt.date(2026, 10, 2), dt.date(2026, 10, 2)),
    ],
    "Eappen": [
        (dt.date(2026, 10, 5), dt.date(2026, 10, 8)),
        (dt.date(2026, 9, 25), dt.date(2026, 9, 25)),
    ],
    "Hurwitz": [
        (dt.date(2026, 9, 25), dt.date(2026, 9, 27)),
    ],
    "Tamirian": [
        (dt.date(2026, 10, 3), dt.date(2026, 10, 4)),
    ],
    "Traboulsi": [
        (dt.date(2026, 11, 13), dt.date(2026, 11, 15)),
        (dt.date(2026, 10, 11), dt.date(2026, 10, 13)),
    ],
    "Anyaso": [
        (dt.date(2026, 10, 3), dt.date(2026, 10, 6)),
        (dt.date(2026, 9, 29), dt.date(2026, 9, 29)),
    ],
}


def load_timeoff():
    """Returns dict: last_name -> list of (start_date, end_date)."""
    return TIME_OFF_REQUESTS
