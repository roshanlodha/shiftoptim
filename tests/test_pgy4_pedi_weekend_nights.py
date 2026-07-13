"""Self-check: Pedi rest encodes as 3-12; history aliases old Pedi name.
Run: python tests/test_pgy4_pedi_weekend_nights.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedulebuilder.pgy4.config import SHIFTS, canonical_shift_name
from schedulebuilder.pgy4 import history


def test_pedi_blocks_next_morning():
    pedi = SHIFTS[4]
    morning = SHIFTS[0]
    assert pedi["end"] == 24 and pedi["duration"] == 9
    end1 = pedi["end"]
    start2 = morning["start"] + 24
    rest = start2 - end1
    required = max(8, pedi["duration"])
    assert rest < required, f"Pedi→morning rest={rest} should be < required={required}"


def test_legacy_pedi_name_counts():
    entry = history.empty_entry()
    entry["shifts"]["Peds Snr 3p-11p (MGH)"] = 2
    totals = history.category_totals(entry)
    assert totals["Pedi"] == 2
    assert canonical_shift_name("Peds Snr 3p-11p (MGH)") == "Peds Snr 3p-12a (MGH)"


if __name__ == "__main__":
    test_pedi_blocks_next_morning()
    test_legacy_pedi_name_counts()
    print("OK")
