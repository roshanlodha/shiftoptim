"""PGY-1 EM vs off-service helpers + soft night target config.
Run: env/bin/python tests/test_pgy1_em_os.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedulebuilder.pgy1.config import (
    is_em_proper,
    is_off_service,
    NIGHT_TARGET_PER_MGH_HALF,
    SHIFT_MIN_PER_HALF,
)


def test_identity():
    assert is_em_proper("Roshan")
    assert not is_off_service("Roshan")
    assert is_off_service("Off Service 1")
    assert not is_em_proper("Off Service 1")
    assert not is_em_proper("Off Service 6")


def test_policy_constants():
    assert SHIFT_MIN_PER_HALF == 10
    assert NIGHT_TARGET_PER_MGH_HALF == 3  # soft target, not hard floor


if __name__ == "__main__":
    test_identity()
    test_policy_constants()
    print("ok")
