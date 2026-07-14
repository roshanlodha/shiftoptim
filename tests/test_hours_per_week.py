"""Smoke test for bridge.hours_per_week. Run: python tests/test_hours_per_week.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webapp.bridge import hours_per_week


def test_hours_per_week():
    assert hours_per_week(0, 2) == 0.0
    assert hours_per_week(70, 0) == 0.0
    # 2 half-blocks = 4 weeks → 140h / 4 = 35
    assert hours_per_week(140, 2) == 35.0
    # 1 half-block = 2 weeks → 36h / 2 = 18
    assert hours_per_week(36, 1) == 18.0


if __name__ == "__main__":
    test_hours_per_week()
    print("OK")
