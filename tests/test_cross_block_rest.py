"""Cross-block rest: prior overnight forbids incompatible day-0 shifts.
Run: python3 tests/test_cross_block_rest.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedulebuilder.pgy4.config import NIGHT_SHIFT, SHIFTS


def _forbidden_day0_shifts(prior_shift_id):
    """Mirrors add_rest_constraints day-0 branch for one resident."""
    info1 = SHIFTS[prior_shift_id]
    end1 = info1["end"] + (24 if info1["type"] == "Overnight" else 0)
    forbidden = []
    for s2, info2 in SHIFTS.items():
        start2 = info2["start"] + 24
        rest_hours = start2 - end1
        required_rest = max(8, info1["duration"])
        if rest_hours < required_rest:
            forbidden.append(s2)
    return forbidden


def test_overnight_prior_forbids_day0_swing():
    forbidden = _forbidden_day0_shifts(NIGHT_SHIFT)
    assert 3 in forbidden, "FF 3p-12a should be forbidden after overnight"


def test_morning_prior_allows_day0_swing():
    assert 3 not in _forbidden_day0_shifts(0)
    assert _forbidden_day0_shifts(0) == []


def test_overnight_to_swing_rest_math():
    night = SHIFTS[NIGHT_SHIFT]
    swing = SHIFTS[3]
    end1 = night["end"] + 24
    start2 = swing["start"] + 24
    rest = start2 - end1
    required = max(8, night["duration"])
    assert rest < required, f"Traboulsi seam: rest={rest}h < required={required}h"


if __name__ == "__main__":
    test_overnight_to_swing_rest_math()
    test_overnight_prior_forbids_day0_swing()
    test_morning_prior_allows_day0_swing()
    print("OK")
