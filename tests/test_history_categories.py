"""Smoke test for schedulebuilder.pgy4.history category_totals. Run:
python tests/test_history_categories.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedulebuilder.pgy4 import history


def test_category_totals():
    entry = history.empty_entry()
    entry["half_blocks_worked"] = 2
    entry["weekend"] = 3
    entry["shifts"]["Acute 7a-4p (MGH)"] = 4
    entry["shifts"]["FF 7a-4p (BWH)"] = 2
    entry["shifts"]["Peds Snr 3p-11p (MGH)"] = 1
    entry["shifts"]["Fast Track 2p-11p (MGH)"] = 5

    totals = history.category_totals(entry)
    assert totals["Morning"] == 6
    assert totals["Pedi"] == 1
    assert totals["FT"] == 5
    assert totals["MGH"] == 10
    assert totals["BWH"] == 2
    assert totals["Weekend"] == 3


if __name__ == "__main__":
    test_category_totals()
    print("OK")
