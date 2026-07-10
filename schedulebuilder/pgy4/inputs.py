"""Parses config.ini: the single admin-editable file holding block dates,
rosters, and time-off requests. Everyone is identified by last name only.

See config.ini at the repo root for the format and inline comments.
This file is PGY-4-specific; other training years will get their own INI later.
"""

import configparser
import datetime as dt
import os

CONFIG_INI = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config.ini",
)


def _parse_date(text):
    month, day, year = (int(x) for x in text.strip().split("/"))
    return dt.date(year, month, day)


def _parse_date_range(text):
    if "-" in text:
        start_text, end_text = text.split("-", 1)
        return _parse_date(start_text), _parse_date(end_text)
    d = _parse_date(text)
    return d, d


def _load_ini():
    parser = configparser.ConfigParser()
    parser.optionxform = str  # preserve case in names (ConfigParser lowercases by default)
    parser.read(CONFIG_INI)
    return parser


def load_block(block):
    """Loads one full block (both halves) from config.ini.

    Returns:
        dates: sorted list of all dates in the block.
        residents: list of resident last names active in at least one half.
        role_on: dict (name, date) -> role string ("MGB" / "MGB Nights" / "Flex"),
                 only present for days the resident is active.
        active_halves: dict name -> number of halves (1 or 2) the resident is active in.
    """
    ini = _load_ini()
    dates_section = f"block {block} dates"
    if dates_section not in ini:
        raise ValueError(f"Block '{block}' has no [{dates_section}] section in config.ini")

    dates = []
    role_on = {}
    active_halves = {}
    residents_seen = []

    for half, date_range in sorted(ini[dates_section].items()):
        start, end = _parse_date_range(date_range)
        half_dates = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
        dates.extend(half_dates)

        roster_section = f"block {block}{half} roster"
        for name, role in ini[roster_section].items():
            if name not in active_halves:
                residents_seen.append(name)
            active_halves[name] = active_halves.get(name, 0) + 1
            for d in half_dates:
                role_on[(name, d)] = role

    dates = sorted(dates)
    return dates, residents_seen, role_on, active_halves


def load_timeoff():
    """Returns dict: resident last name -> list of (start_date, end_date)."""
    ini = _load_ini()
    if "time off" not in ini:
        return {}
    requests = {}
    for name, raw in ini["time off"].items():
        requests[name] = [_parse_date_range(part) for part in raw.split(",") if part.strip()]
    return requests
