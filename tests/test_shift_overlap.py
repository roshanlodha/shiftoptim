"""Shift overlap fraction for buddy matching.
Run: python3 tests/test_shift_overlap.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webapp import bridge


def test_exact_match():
    assert bridge.overlap_fraction(11, 20, 9, 11, 20) == 1.0


def test_pgy1_ft_vs_pgy4_fast_track():
    # PGY-1 MGH Jr FT 11a-8p vs PGY-4 Fast Track 2p-11p (MGH)
    frac = bridge.overlap_fraction(11, 20, 9, 14, 23)
    assert frac > 0.5, f"expected buddy overlap, got {frac}"


def test_under_threshold():
    # 7a-4p vs 1p-11p — overlap 3h of 9h ref ≈ 33%
    frac = bridge.overlap_fraction(7, 16, 9, 13, 23)
    assert frac < 0.5


def test_overnight_wrap():
    rs, re = bridge._hour_interval(23, 7)
    assert re == 31
    frac = bridge.overlap_fraction(23, 7, 8, 23, 7)
    assert frac == 1.0


def test_different_site_zero():
    # overlap math same; site filter is in find_shift_buddies — interval still valid
    assert bridge.overlap_fraction(11, 20, 9, 11, 20) == 1.0


if __name__ == "__main__":
    test_exact_match()
    test_pgy1_ft_vs_pgy4_fast_track()
    test_under_threshold()
    test_overnight_wrap()
    test_different_site_zero()
    print("ok")
