from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

@dataclass(frozen=True)
class Shift:
    uid: str                  # ICS UID (unique key)
    owner: str                # resident name (filename stem or mapping)
    t_start: datetime         # tz-aware
    t_end: datetime           # tz-aware
    loc: Optional[str]        # "MGH" | "BWH" | None (None = jeopardy/backup)
    type: Optional[str]       # "Morning" | "Swing" | "Overnight" | None
    work_date: date           # calendar date of t_start (LOCAL) -> streak key
    summary: str              # raw SUMMARY text
    is_jeopardy: bool         # True = location/time-agnostic backup shift

# Jeopardy shifts are fully swappable. loc=None and type=None mean they are
# excluded from the location and time satisfaction scores, but their work_date
# still counts toward the consecutive-days streak and toward feasibility.

@dataclass
class Resident:
    name: str
    loc_pref: str             # "MGH" | "BWH" | "ANY"
    loc_weight: float
    type_pref: str            # "Morning" | "Swing" | "Overnight" | "ANY"
    type_weight: float
    days_pref: int            # ideal consecutive days, 3..6
    days_weight: float
    days_off: frozenset[date] # dates that MUST remain shift-free

# A schedule assignment: resident name -> set of Shift uids they own.
# Keep the authoritative store as: dict[str, set[str]] (name -> {uid}).
# Plus a uid -> Shift lookup table.

@dataclass
class Schedule:
    assignment: dict[str, set[str]]      # resident name -> set of shift uids
    shifts: dict[str, Shift]             # uid -> Shift
    residents: dict[str, Resident]       # name -> Resident

    def shifts_of(self, name: str) -> list[Shift]:
        return [self.shifts[u] for u in self.assignment[name]]