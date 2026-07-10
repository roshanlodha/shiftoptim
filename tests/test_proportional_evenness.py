"""Smoke test for proportional rate scaling in the evenness objective."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedulebuilder.pgy4.objective import rate_scaled


def test_equal_rates_match():
    h_max = 4
    assert rate_scaled(8, 2, h_max) == rate_scaled(16, 4, h_max)
    assert rate_scaled(12, 3, h_max) == rate_scaled(8, 2, h_max)


def test_unequal_rates_differ():
    h_max = 4
    assert rate_scaled(10, 2, h_max) > rate_scaled(12, 4, h_max)


if __name__ == "__main__":
    test_equal_rates_match()
    test_unequal_rates_differ()
    print("OK")
