from .config import STREAK_BETA
from .feasibility import _streaks
from .models import Shift, Resident


def phi_loc(shifts: list[Shift], r: Resident) -> float:
    # Jeopardy shifts (loc is None) are location-agnostic: excluded from both
    # numerator and denominator so they neither help nor hurt this score.
    located = [s for s in shifts if s.loc is not None]
    if r.loc_pref == "ANY" or not located:
        return 1.0
    return sum(1 for s in located if s.loc == r.loc_pref) / len(located)


def phi_type(shifts: list[Shift], r: Resident) -> float:
    # Jeopardy shifts (type is None) are time-agnostic: excluded from this score.
    typed = [s for s in shifts if s.type is not None]
    if r.type_pref == "ANY" or not typed:
        return 1.0
    return sum(1 for s in typed if s.type == r.type_pref) / len(typed)


def phi_str(shifts: list[Shift], r: Resident) -> float:
    runs = _streaks({s.work_date for s in shifts})
    if not runs:
        return 1.0
    mean_dev = sum(abs(L - r.days_pref) for L in runs) / len(runs)
    return max(0.0, 1.0 - mean_dev / STREAK_BETA)


def utility(shifts: list[Shift], r: Resident) -> float:
    return (r.loc_weight  * phi_loc(shifts, r)
          + r.type_weight * phi_type(shifts, r)
          + r.days_weight * phi_str(shifts, r))
