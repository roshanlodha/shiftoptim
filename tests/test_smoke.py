from pathlib import Path
from shiftmaxxer.ingest import load_preferences, build_schedule
from shiftmaxxer.optimizer import optimize
from shiftmaxxer.render import render_html
import shiftmaxxer.config as config

def test_load_preferences_normalization():
    # Keep track of the original config setting
    orig_ignore = config.IGNORE_WEIGHT
    try:
        config.IGNORE_WEIGHT = True
        residents = load_preferences(Path("data/preferences.csv"))
        
        # Roshan has MGH (weight 1), Morning (weight 0.5), days_weight 1.
        # Under IGNORE_WEIGHT = True, all three are overridden to 1.0.
        # Sum = 3.0. Normalized weights should be 1/3 each.
        roshan = residents["roshan"]
        assert abs(roshan.loc_weight - 1/3) < 1e-6
        assert abs(roshan.type_weight - 1/3) < 1e-6
        assert abs(roshan.days_weight - 1/3) < 1e-6

        # Justin has BWH (weight 1), Swing (weight 1), days_weight 1.
        # Under IGNORE_WEIGHT = True, all three are 1.0.
        # Sum = 3.0. Normalized weights should be 1/3 each.
        justin = residents["justin"]
        assert abs(justin.loc_weight - 1/3) < 1e-6
        assert abs(justin.type_weight - 1/3) < 1e-6
        assert abs(justin.days_weight - 1/3) < 1e-6
    finally:
        config.IGNORE_WEIGHT = orig_ignore

def test_end_to_end_pipeline():
    sched = build_schedule(Path("data/ics"), Path("data/preferences.csv"))
    original_assignment = {n: set(uids) for n, uids in sched.assignment.items()}
    log = optimize(sched, K=10, n_max=2)
    html = render_html(sched, log, original_assignment)
    assert html is not None
    assert "/*__INJECT_DATA__*/" not in html
    assert "class=\"md3-segmented-button" in html

def test_resident_metrics_payload():
    from shiftmaxxer.render import build_payload
    sched = build_schedule(Path("data/ics"), Path("data/preferences.csv"))
    original_assignment = {n: set(uids) for n, uids in sched.assignment.items()}
    log = optimize(sched, K=10, n_max=2)
    payload = build_payload(sched, log, original_assignment)
    
    roshan = payload["residents"]["roshan"]
    assert "loc" in roshan
    assert "orig" in roshan["loc"]
    assert "opt" in roshan["loc"]
    assert "type" in roshan
    assert "streak" in roshan
    assert "happiness" in roshan
    
    # Check startHour and endHour are in shifts
    for suid, s in payload["shifts"].items():
        assert "startHour" in s
        assert "endHour" in s

def test_midnight_shift_end_hour():
    from shiftmaxxer.render import build_payload
    sched = build_schedule(Path("data/ics"), Path("data/preferences.csv"))
    original_assignment = {n: set(uids) for n, uids in sched.assignment.items()}
    payload = build_payload(sched, [], original_assignment)
    
    # Justin has 8eff5ce7-3e1d-47ea-89f2-fcb1b1432788 (BWH Jr. - Exe Jr 3p-12a)
    # which starts at 3:00 PM on 2026-06-25 and ends at 12:00 AM on 2026-06-26.
    # Its endHour should be overridden to 24.0.
    target_uid = "8eff5ce7-3e1d-47ea-89f2-fcb1b1432788"
    assert target_uid in payload["shifts"]
    s = payload["shifts"][target_uid]
    assert s["startHour"] == 15.0
    assert s["endHour"] == 24.0


def test_days_off_streak_calculation():
    from datetime import date, timedelta
    from shiftmaxxer.render import _off_streaks
    
    timeline = [
        date(2026, 6, 22), # Mon
        date(2026, 6, 23), # Tue
        date(2026, 6, 24), # Wed
        date(2026, 6, 25), # Thu
        date(2026, 6, 26), # Fri
        date(2026, 6, 27), # Sat
        date(2026, 6, 28), # Sun
    ]
    worked = {
        date(2026, 6, 22),
        date(2026, 6, 23),
        date(2026, 6, 24),
        date(2026, 6, 26),
    }
    runs = _off_streaks(timeline, worked)
    assert runs == [1, 2]

    # User's example: 5 worked, 3 off, 3 worked, 2 off.
    timeline_user = [date(2026, 6, 22) + timedelta(days=i) for i in range(13)]
    worked_user = {timeline_user[i] for i in [0, 1, 2, 3, 4, 8, 9, 10]}
    runs_user = _off_streaks(timeline_user, worked_user)
    assert runs_user == [3, 2]
    avg = sum(runs_user) / len(runs_user)
    assert avg == 2.5



