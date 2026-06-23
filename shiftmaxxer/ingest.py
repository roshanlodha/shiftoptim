from icalendar import Calendar
from dateutil import tz
from datetime import datetime
from pathlib import Path
import pandas as pd
import re
import urllib.request
import urllib.error

from . import config
from .config import (LOC_PREFIX_LEN, VALID_LOCATIONS, JEOPARDY_KEYWORDS,
                     MORNING_START, SWING_START, OVERNIGHT_START, LOCAL_TZ, NO_PREF)
from .models import Shift, Resident, Schedule

LOCAL = tz.gettz(LOCAL_TZ)


def classify_type(start: datetime) -> str:
    h = start.hour
    if MORNING_START <= h < SWING_START:
        return "Morning"
    if SWING_START <= h < OVERNIGHT_START:
        return "Swing"
    return "Overnight"   # h >= 18 or h < 4


def parse_location(raw: str) -> str:
    code = (raw or "").strip()[:LOC_PREFIX_LEN].upper()
    if code not in VALID_LOCATIONS:
        raise ValueError(f"Unknown location prefix: {raw!r}")
    return code


def is_jeopardy(summary: str) -> bool:
    s = (summary or "").lower()
    return any(k in s for k in JEOPARDY_KEYWORDS)


def parse_ics_file(path: Path, owner: str) -> list[Shift]:
    cal = Calendar.from_ical(path.read_bytes())
    shifts = []
    for comp in cal.walk("VEVENT"):
        start = comp.decoded("DTSTART")
        end = comp.decoded("DTEND")
        # Ensure tz-aware in LOCAL; ICS uses fixed -0400 (EDT).
        start = start.astimezone(LOCAL) if start.tzinfo else start.replace(tzinfo=LOCAL)
        end = end.astimezone(LOCAL) if end.tzinfo else end.replace(tzinfo=LOCAL)
        if config.START_DATE != "":
            if isinstance(config.START_DATE, datetime):
                start_filter = config.START_DATE if config.START_DATE.tzinfo else config.START_DATE.replace(tzinfo=LOCAL)
            else:
                start_filter = datetime.combine(config.START_DATE, datetime.min.time()).replace(tzinfo=LOCAL)
            if start < start_filter:
                continue
        summary = str(comp.get("SUMMARY", ""))
        jeop = is_jeopardy(summary)
        shifts.append(Shift(
            uid=str(comp.get("UID")),
            owner=owner,
            t_start=start,
            t_end=end,
            # Jeopardy shifts are location/time-agnostic -> None on both.
            loc=None if jeop else parse_location(str(comp.get("LOCATION", ""))),
            type=None if jeop else classify_type(start),
            work_date=start.date(),
            summary=summary,
            is_jeopardy=jeop,
        ))
    return shifts


def load_all_ics(ics_dir: Path) -> list[Shift]:
    out = []
    for p in sorted(ics_dir.glob("*.ics")):
        out.extend(parse_ics_file(p, owner=p.stem.lower().strip()))
    return out


def _parse_days_off(cell: str) -> frozenset:
    if not isinstance(cell, str) or not cell.strip():
        return frozenset()
    dates = re.findall(r"(\d{2}/\d{2}/\d{4})", cell)
    return frozenset(datetime.strptime(d, "%m/%d/%Y").date() for d in dates)


def _norm_pref(value: str, allowed: set[str]) -> str:
    v = str(value).strip().upper()
    table = {a.upper(): a for a in allowed}
    return table.get(v, NO_PREF)


def load_preferences(csv_path) -> dict[str, Resident]:
    df = pd.read_csv(csv_path)
    expected_cols = [
        "timestamp",
        "resident",
        "location_pref",
        "time_pref",
        "days_off",
        "location_weight",
        "time_weight",
        "days_pref",
        "days_weight",
        "calendar_ics",
    ]
    if len(df.columns) == len(expected_cols):
        df.columns = expected_cols
    else:
        raise ValueError(
            f"Expected {len(expected_cols)} columns in preferences CSV, found {len(df.columns)}: {list(df.columns)}"
        )
    residents = {}
    for _, row in df.iterrows():
        loc_pref = _norm_pref(row["location_pref"], {"MGH", "BWH"})
        # Overnight is not an allowed preference (no one wants overnights);
        # anything other than Morning/Swing normalizes to ANY (no preference).
        type_pref = _norm_pref(row["time_pref"], {"Morning", "Swing"})

        # Zero-out weights whose preference is ANY.
        w_loc = 0.0 if loc_pref == NO_PREF else float(row["location_weight"])
        w_typ = 0.0 if type_pref == NO_PREF else float(row["time_weight"])

        # Determine if streak preference is declared
        days_pref_raw = str(row["days_pref"]).strip().lower()
        if days_pref_raw in ("", "no preference", "any", "none"):
            w_str = 0.0
            days_pref_val = 5
        else:
            w_str = float(row["days_weight"])
            try:
                days_pref_val = int(float(row["days_pref"]))
                days_pref_val = int(max(3, min(6, days_pref_val)))
            except (ValueError, TypeError):
                days_pref_val = 5

        if config.IGNORE_WEIGHT:
            w_loc = 1.0 if w_loc > 0 else 0.0
            w_typ = 1.0 if w_typ > 0 else 0.0
            w_str = 1.0 if w_str > 0 else 0.0

        total = w_loc + w_typ + w_str
        if total > 0:
            w_loc, w_typ, w_str = w_loc/total, w_typ/total, w_str/total

        name = str(row["resident"]).lower().strip()
        residents[name] = Resident(
            name=name,
            loc_pref=loc_pref, loc_weight=w_loc,
            type_pref=type_pref, type_weight=w_typ,
            days_pref=days_pref_val,
            days_weight=w_str,
            days_off=_parse_days_off(row["days_off"]),
        )
    return residents


def _extract_gdrive_id(url: str) -> str | None:
    """Extract Google Drive file ID from various link formats."""
    m = re.search(r'id=([a-zA-Z0-9_-]+)', str(url))
    if m:
        return m.group(1)
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', str(url))
    if m:
        return m.group(1)
    return None


def download_ics_from_csv(csv_path: Path, ics_dir: Path) -> None:
    """Download ICS files from Google Drive links in preferences CSV."""
    df = pd.read_csv(csv_path)
    expected_cols = [
        "timestamp", "resident", "location_pref", "time_pref",
        "days_off", "location_weight", "time_weight",
        "days_pref", "days_weight", "calendar_ics",
    ]
    if len(df.columns) == len(expected_cols):
        df.columns = expected_cols
    else:
        return  # can't parse → skip download

    ics_dir.mkdir(parents=True, exist_ok=True)
    for _, row in df.iterrows():
        name = str(row["resident"]).strip()
        url = str(row.get("calendar_ics", "")).strip()
        if not url or url == "nan":
            continue
        file_id = _extract_gdrive_id(url)
        if not file_id:
            print(f"  skip {name}: can't parse Drive link")
            continue
        dest = ics_dir / f"{name}.ics"
        if dest.exists():
            continue  # already have it
        dl_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        print(f"  downloading {name}.ics ...")
        try:
            urllib.request.urlretrieve(dl_url, dest)
        except urllib.error.URLError as e:
            print(f"  FAILED {name}: {e}")


def build_schedule(ics_dir, csv_path) -> Schedule:
    # Auto-download ICS files from Drive links in CSV.
    download_ics_from_csv(Path(csv_path), Path(ics_dir))

    shifts_list = load_all_ics(ics_dir)
    residents = load_preferences(csv_path)
    shifts = {s.uid: s for s in shifts_list}
    assignment = {name: set() for name in residents}
    for s in shifts_list:
        assignment.setdefault(s.owner, set()).add(s.uid)
    # Every ics owner must exist in preferences; if not, create indifferent resident.
    for owner in assignment:
        if owner not in residents:
            residents[owner] = Resident(owner, "ANY", 0, "ANY", 0, 4, 0, frozenset())
    return Schedule(assignment=assignment, shifts=shifts, residents=residents)
