"""Plain-assert smoke test for schedulebuilder.history: JSON round-trip and
category_totals math. Run directly: python tests/test_history_categories.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedulebuilder import config, history


def test_missing_file_gives_empty_history():
    config.HISTORY_JSON = os.path.join(tempfile.mkdtemp(), "does_not_exist.json")
    assert history.load_history() == {}


def test_round_trip_and_category_totals():
    config.HISTORY_JSON = os.path.join(tempfile.mkdtemp(), "history.json")

    entry = history.empty_entry()
    entry["half_blocks_worked"] = 2
    entry["weekend"] = 3
    entry["shifts"]["Acute 7a-4p (MGH)"] = 4   # Morning, MGH
    entry["shifts"]["FF 7a-4p (BWH)"] = 2      # Morning, BWH
    entry["shifts"]["Peds Snr 3p-11p (MGH)"] = 1  # Swing, MGH, Pedi
    entry["shifts"]["Fast Track 2p-11p (MGH)"] = 5  # Swing, MGH, FT

    history.save_history({"Alice": entry})
    loaded = history.load_history()
    assert loaded["Alice"]["half_blocks_worked"] == 2
    assert loaded["Alice"]["weekend"] == 3
    assert loaded["Alice"]["shifts"]["Acute 7a-4p (MGH)"] == 4

    totals = history.category_totals(loaded["Alice"])
    assert totals["Morning"] == 4 + 2
    assert totals["Pedi"] == 1
    assert totals["FT"] == 5
    assert totals["MGH"] == 4 + 1 + 5
    assert totals["BWH"] == 2
    assert totals["Weekend"] == 3


if __name__ == "__main__":
    test_missing_file_gives_empty_history()
    test_round_trip_and_category_totals()
    print("OK")
