from datetime import date
from .config import MIN_REST, MAX_CONSECUTIVE_DAYS
from .models import Shift


def _streaks(work_dates: set[date]) -> list[int]:
    """Return lengths of maximal consecutive-day runs."""
    if not work_dates:
        return []
    ordered = sorted(work_dates)
    lengths, run = [], 1
    for prev, cur in zip(ordered, ordered[1:]):
        if (cur - prev).days == 1:
            run += 1
        else:
            lengths.append(run); run = 1
    lengths.append(run)
    return lengths


def is_valid(shifts: list[Shift], days_off: frozenset[date]) -> bool:
    if not shifts:
        return True

    # (c) Day-off: no shift may fall on a declared day off.
    for s in shifts:
        if s.work_date in days_off:
            return False

    ordered = sorted(shifts, key=lambda s: s.t_start)

    # (a) Minimum rest between chronologically adjacent shifts.
    #     (Also forbids overlap, since gap >= 12h > 0.)
    for a, b in zip(ordered, ordered[1:]):
        if b.t_start - a.t_end < MIN_REST:
            return False

    # (b) Maximum consecutive working days.
    if any(L > MAX_CONSECUTIVE_DAYS for L in _streaks({s.work_date for s in shifts})):
        return False

    return True
