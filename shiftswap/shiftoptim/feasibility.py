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


def _count_violations(shifts: list[Shift]) -> int:
    """Count ACGME rest + streak violations. Day-off is handled separately as a
    hard constraint, so it is intentionally excluded here."""
    if not shifts:
        return 0
    ordered = sorted(shifts, key=lambda s: s.t_start)
    rest = sum(1 for a, b in zip(ordered, ordered[1:]) if b.t_start - a.t_end < MIN_REST)
    streak = sum(1 for L in _streaks({s.work_date for s in shifts})
                 if L > MAX_CONSECUTIVE_DAYS)
    return rest + streak


def _has_overlap(shifts: list[Shift]) -> bool:
    """Return True if any two shifts have overlapping time windows."""
    ordered = sorted(shifts, key=lambda s: s.t_start)
    for a, b in zip(ordered, ordered[1:]):
        if b.t_start < a.t_end:
            return True
    return False


def is_valid_swap(proposed: list[Shift], current: list[Shift],
                  days_off: frozenset[date]) -> bool:
    """A swap is acceptable if it does not WORSEN feasibility relative to the
    resident's current schedule. Real-world rosters frequently carry pre-existing
    rest violations (e.g. an 11a-8p shift followed by a next-day 7a shift = 11h
    rest); those are grandfathered. Day-off remains an absolute hard constraint:
    a proposed shift may never land on a declared day off. Overlapping shifts
    (double-booking) are also an absolute hard constraint and are never allowed.
    Residents also may not receive shifts beyond their current last shift date."""
    # Personal schedule horizon: no one can extend beyond their last shift date.
    if proposed and current:
        if max(s.work_date for s in proposed) > max(s.work_date for s in current):
            return False
    # Day-off: always hard, never allowed.
    for s in proposed:
        if s.work_date in days_off:
            return False
    # Overlapping shifts: always hard, never allowed regardless of prior state.
    if _has_overlap(proposed):
        return False
    # Rest + streak: only reject if the swap introduces NEW violations.
    return _count_violations(proposed) <= _count_violations(current)
