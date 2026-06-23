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
        roshan = residents["roshan lodha"]
        assert abs(roshan.loc_weight - 1/3) < 1e-6
        assert abs(roshan.type_weight - 1/3) < 1e-6
        assert abs(roshan.days_weight - 1/3) < 1e-6

        # Justin has BWH (weight 1), Swing (weight 1), days_weight 1.
        # Under IGNORE_WEIGHT = True, all three are 1.0.
        # Sum = 3.0. Normalized weights should be 1/3 each.
        if "justin" in residents:
            justin = residents["justin"]
            assert abs(justin.loc_weight - 1/3) < 1e-6
            assert abs(justin.type_weight - 1/3) < 1e-6
            assert abs(justin.days_weight - 1/3) < 1e-6
    finally:
        config.IGNORE_WEIGHT = orig_ignore

def test_end_to_end_pipeline():
    sched = build_schedule(Path("data/ics"), Path("data/preferences.csv"))
    original_assignment = {n: set(uids) for n, uids in sched.assignment.items()}
    log = optimize(sched, max_swaps_per_person=-1, n_max=2)
    html = render_html(sched, log, original_assignment)
    assert html is not None
    assert "/*__INJECT_DATA__*/" not in html
    assert "class=\"md3-segmented-button" in html

def test_resident_metrics_payload():
    from shiftmaxxer.render import build_payload
    sched = build_schedule(Path("data/ics"), Path("data/preferences.csv"))
    original_assignment = {n: set(uids) for n, uids in sched.assignment.items()}
    log = optimize(sched, max_swaps_per_person=-1, n_max=2)
    payload = build_payload(sched, log, original_assignment)
    
    roshan = payload["residents"]["roshan lodha"]
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
    
    # Brian has 73048cf3-ec0a-48cc-933b-598134e736cf (BWH Jr. - Exe Jr 3p-12a)
    # which starts at 3:00 PM on 2026-07-03 and ends at 12:00 AM on 2026-07-04.
    # Its endHour should be overridden to 24.0.
    target_uid = "73048cf3-ec0a-48cc-933b-598134e736cf"
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


def _make_shift(uid, owner, work_date, is_jeopardy=False, loc="MGH", stype="Morning"):
    """Helper: build a minimal Shift for unit tests."""
    from datetime import datetime, timedelta
    from dateutil import tz
    from shiftmaxxer.models import Shift
    LOCAL = tz.gettz("America/New_York")
    t_start = datetime(work_date.year, work_date.month, work_date.day, 7, 0, tzinfo=LOCAL)
    t_end = t_start + timedelta(hours=9)
    return Shift(
        uid=uid, owner=owner, t_start=t_start, t_end=t_end,
        loc=None if is_jeopardy else loc,
        type=None if is_jeopardy else stype,
        work_date=work_date, summary="test", is_jeopardy=is_jeopardy,
    )


def test_jeopardy_isolation_no_cross_type_edges():
    """Jeopardy shifts must never have trade-graph edges to/from regular shifts."""
    from datetime import date
    from shiftmaxxer.models import Resident, Schedule
    from shiftmaxxer.graph import build_trade_graph

    d1, d2 = date(2026, 7, 1), date(2026, 7, 2)
    s_reg = _make_shift("reg1", "alice", d1, is_jeopardy=False, loc="BWH")
    s_jep = _make_shift("jep1", "bob",   d2, is_jeopardy=True)

    alice = Resident("alice", "MGH", 0.5, "Morning", 0.5, 4, 0.0, frozenset())
    bob   = Resident("bob",   "MGH", 0.5, "Morning", 0.5, 4, 0.0, frozenset())

    sched = Schedule(
        assignment={"alice": {"reg1"}, "bob": {"jep1"}},
        shifts={"reg1": s_reg, "jep1": s_jep},
        residents={"alice": alice, "bob": bob},
    )

    orig_allow = config.ALLOW_JEOPARDY_SWAPS
    try:
        config.ALLOW_JEOPARDY_SWAPS = True
        G = build_trade_graph(sched)
        # No edge in either direction between a jeopardy and a regular shift.
        assert not G.has_edge("reg1", "jep1"), "regular→jeopardy edge should not exist"
        assert not G.has_edge("jep1", "reg1"), "jeopardy→regular edge should not exist"
    finally:
        config.ALLOW_JEOPARDY_SWAPS = orig_allow


def test_jeopardy_swaps_enabled_same_type():
    """Two jeopardy shifts owned by different residents CAN form edges."""
    from datetime import date
    from shiftmaxxer.models import Resident, Schedule
    from shiftmaxxer.graph import build_trade_graph

    d1, d2 = date(2026, 7, 1), date(2026, 7, 2)
    s1 = _make_shift("j1", "alice", d1, is_jeopardy=True)
    s2 = _make_shift("j2", "bob",   d2, is_jeopardy=True)

    # Both residents are indifferent — swapping is feasible and non-harmful.
    alice = Resident("alice", "ANY", 0.0, "ANY", 0.0, 4, 1.0, frozenset())
    bob   = Resident("bob",   "ANY", 0.0, "ANY", 0.0, 4, 1.0, frozenset())

    sched = Schedule(
        assignment={"alice": {"j1"}, "bob": {"j2"}},
        shifts={"j1": s1, "j2": s2},
        residents={"alice": alice, "bob": bob},
    )

    orig_allow = config.ALLOW_JEOPARDY_SWAPS
    try:
        config.ALLOW_JEOPARDY_SWAPS = True
        G = build_trade_graph(sched)
        # At least one direction should have an edge (swap is neutral/improving).
        has_edge = G.has_edge("j1", "j2") or G.has_edge("j2", "j1")
        assert has_edge, "same-type jeopardy swap should produce at least one edge"
    finally:
        config.ALLOW_JEOPARDY_SWAPS = orig_allow


def test_jeopardy_swaps_disabled_pins_shifts():
    """When ALLOW_JEOPARDY_SWAPS is False, jeopardy shifts have zero edges."""
    from datetime import date
    from shiftmaxxer.models import Resident, Schedule
    from shiftmaxxer.graph import build_trade_graph

    d1, d2 = date(2026, 7, 1), date(2026, 7, 2)
    s1 = _make_shift("j1", "alice", d1, is_jeopardy=True)
    s2 = _make_shift("j2", "bob",   d2, is_jeopardy=True)

    alice = Resident("alice", "ANY", 0.0, "ANY", 0.0, 4, 1.0, frozenset())
    bob   = Resident("bob",   "ANY", 0.0, "ANY", 0.0, 4, 1.0, frozenset())

    sched = Schedule(
        assignment={"alice": {"j1"}, "bob": {"j2"}},
        shifts={"j1": s1, "j2": s2},
        residents={"alice": alice, "bob": bob},
    )

    orig_allow = config.ALLOW_JEOPARDY_SWAPS
    try:
        config.ALLOW_JEOPARDY_SWAPS = False
        G = build_trade_graph(sched)
        assert not G.has_edge("j1", "j2"), "pinned jeopardy should have no outgoing edges"
        assert not G.has_edge("j2", "j1"), "pinned jeopardy should have no outgoing edges"
        # Verify zero total edges involving jeopardy nodes.
        assert G.degree("j1") == 0, "pinned jeopardy node j1 should be isolated"
        assert G.degree("j2") == 0, "pinned jeopardy node j2 should be isolated"
    finally:
        config.ALLOW_JEOPARDY_SWAPS = orig_allow

